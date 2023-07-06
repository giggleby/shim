# Copyright 2018 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.
"""Handler for ingestion."""

import collections
import hashlib
import json
import logging
import os
import os.path
import textwrap
from typing import Collection, Mapping, NamedTuple, Optional, Set, Union

import urllib3

from cros.factory.hwid.service.appengine import api_connector
from cros.factory.hwid.service.appengine import auth
from cros.factory.hwid.service.appengine.data import config_data as config_data_module
from cros.factory.hwid.service.appengine.data import decoder_data as decoder_data_module
from cros.factory.hwid.service.appengine.data import payload_data
from cros.factory.hwid.service.appengine import git_util
from cros.factory.hwid.service.appengine import hwid_action_manager as hwid_action_manager_module
from cros.factory.hwid.service.appengine import hwid_repo
from cros.factory.hwid.service.appengine import memcache_adapter
from cros.factory.hwid.service.appengine.proto import ingestion_pb2  # pylint: disable=no-name-in-module
from cros.factory.hwid.service.appengine import verification_payload_generator as vpg_module
from cros.factory.hwid.v3 import filesystem_adapter
from cros.factory.hwid.v3 import name_pattern_adapter
from cros.factory.probe_info_service.app_engine import protorpc_utils
from cros.factory.utils import json_utils


GOLDENEYE_MEMCACHE_NAMESPACE = 'SourceGoldenEye'


class PayloadGenerationException(protorpc_utils.ProtoRPCException):
  """Exception to group similar exceptions for error reporting."""

  def __init__(self, msg):
    super().__init__(protorpc_utils.RPCCanonicalErrorCode.INTERNAL, detail=msg)


_HWIDIngestionProtoRPCShardBase = protorpc_utils.CreateProtoRPCServiceShardBase(
    'HwidIngestionProtoRPCShardBase',
    ingestion_pb2.DESCRIPTOR.services_by_name['HwidIngestion'])


def _GetHWIDMainCommitIfChanged(
    hwid_repo_manager: hwid_repo.HWIDRepoManager,
    payload_data_manager: payload_data.PayloadDataManager,
    force_update: bool) -> Optional[str]:

  hwid_main_commit = hwid_repo_manager.GetMainCommitID()
  latest_commit = payload_data_manager.GetLatestHWIDMainCommit()

  if latest_commit == hwid_main_commit and not force_update:
    logging.info('The HWID main commit %s is already processed, skipped',
                 hwid_main_commit)
    return None
  return hwid_main_commit


# TODO(kevinptt): Unify "dryrun_upload" and "abandon_cl" into single state.
def _TryCreateCL(dryrun_upload: bool, abandon_cl: bool,
                 setting: config_data_module.CLSetting, author: str,
                 reviewers: Collection[str], ccs: Collection[str],
                 files: Mapping[str, Union[str,
                                           bytes]], commit_msg: str) -> None:
  """Tries to create a CL if possible.

  Use git_util to create CL in repo for generated payloads.  If something goes
  wrong, email to the hw-checker group.

  Args:
    dryrun_upload: Do everything except actually upload the CL.
    abandon_cl: Abandon created CL after uploading.
    setting: The setting to the repo.
    author: The CL author.
    reviewers: The additional reviewers.
    ccs: The additional CC reviewers.
    files: A path-content mapping of payload files.
    commit_msg: Commit message of the CL.
  """

  git_url = f'{setting.repo_host}/{setting.project}'
  branch = setting.branch or git_util.GetCurrentBranch(
      setting.review_host, setting.project, git_util.GetGerritAuthCookie())
  git_files = [(os.path.join(setting.prefix,
                             filepath), git_util.NORMAL_FILE_MODE, filecontent)
               for filepath, filecontent in files.items()]

  if dryrun_upload:
    # file_info = (file_path, mode, content)
    file_paths = '\n'.join('  ' + file_info[0] for file_info in git_files)
    dryrun_upload_info = textwrap.dedent(f"""\
        Dryrun upload to {setting.project}
        git_url: {git_url}
        branch: {branch}
        author: {author}
        reviewers: {reviewers}
        ccs: {ccs}
        commit msg:
        {commit_msg}
        update file paths:
        {file_paths}
    """)
    logging.debug(dryrun_upload_info)
  else:
    auth_cookie = git_util.GetGerritAuthCookie()
    try:
      change_id, _ = git_util.CreateCL(
          git_url, auth_cookie, branch, git_files, author, author, commit_msg,
          reviewers, ccs, topic=setting.topic, hashtags=setting.hashtags)
      if abandon_cl:  # Abandon the test CL to prevent confusion
        try:
          git_util.AbandonCL(setting.review_host, auth_cookie, change_id)
        except (git_util.GitUtilException, urllib3.exceptions.HTTPError) as ex:
          logging.error('Cannot abandon CL for %r: %r', change_id, str(ex))
    except git_util.GitUtilNoModificationException:
      logging.debug('No modification is made, skipped')
    except git_util.GitUtilException as ex:
      logging.error('CL is not created: %r', str(ex))
      raise PayloadGenerationException('CL is not created') from ex


class _HWIDSelectionPayloadResult(NamedTuple):
  """Handles generated HWID selection payload.

  Attributes:
    generated_file_contents: A string-to-string dictionary which represents the
        files that should be committed into the bsp package.
    payload_hash: Hash of the payload.
  """
  generated_file_contents: Mapping[str, Union[str, bytes]]
  payload_hash: str


class HWIDSelectionPayloadManager:
  """A class which manages the status of HWID feature matching payloads."""

  def __init__(
      self, hwid_repo_manager: hwid_repo.HWIDRepoManager,
      hwid_action_manager: hwid_action_manager_module.HWIDActionManager,
      hsp_data_manager: payload_data.PayloadDataManager):
    self._hwid_repo_manager = hwid_repo_manager
    self._hwid_action_manager = hwid_action_manager
    self._hsp_data_manager = hsp_data_manager

  def Sync(self, force_update: bool, dryrun_upload: bool, abandon_cl: bool,
           limit_models: Collection[str]) -> Mapping[str, str]:
    """Updates generated payloads to private overlays.

    This method will handle the payload creation request as follows:

      1. Check if the main commit of HWID DB is the same as cached one on
         Datastore and exit if they match.
      2. Generate a dict of board->payload_hash.
      3. Check if the cached payload hashes of boards in Datastore and generated
         ones match.
      4. Create a CL for each board if the generated payload hash differs from
         cached one.

    To prevent duplicate error notification or unnecessary check next time, this
    method will store the commit hash and payload hash in Datastore once
    generated.

    Args:
      force_update: Always getting payload_hash_mapping for testing purpose.
      dryrun_upload: Do everything except actually upload the CL.
      abandon_cl: Abandon created CL after uploading.
      limit_models: A set of models requiring payload generation, empty if
        unlimited.  A model will be ignored if it is not vpg-enabled.
    """

    logging.info('HWIDSelectionPayloadManager start syncing')
    hwid_main_commit = _GetHWIDMainCommitIfChanged(
        self._hwid_repo_manager, self._hsp_data_manager, force_update)
    if not hwid_main_commit:
      return {}
    logging.info('HWIDSelectionPayloadManager sync with HWID commit %s',
                 hwid_main_commit)
    self._hsp_data_manager.SetLatestHWIDMainCommit(hwid_main_commit)
    boards_payloads = self._GeneratePayloads(limit_models)
    payload_hash_mapping = {}
    service_account_name, unused_token = git_util.GetGerritCredentials()
    author = f'chromeoshwid <{service_account_name}>'
    reviewers = self._hsp_data_manager.GetCLReviewers()
    ccs = self._hsp_data_manager.GetCLCCs()
    commit_msg = textwrap.dedent(f"""\
        feature-management-bsp: update payload from hwid

        From chromeos/chromeos-hwid: {hwid_main_commit}
    """)
    for board, payloads in boards_payloads.items():
      setting = config_data_module.CreateHWIDSelectionPayloadSettings(board)
      if self._ShouldUpdatePayload(board, payloads, force_update):
        new_files = payloads.generated_file_contents
        _TryCreateCL(dryrun_upload, abandon_cl, setting, author, reviewers, ccs,
                     new_files, commit_msg)
        payload_hash_mapping[board] = payloads.payload_hash
        self._hsp_data_manager.SetLatestPayloadHash(board,
                                                    payloads.payload_hash)

    logging.info('HWIDSelectionPayloadManager sync successfully')
    return payload_hash_mapping

  @classmethod
  def _JsonHash(cls, data) -> str:
    """Calculates the SHA1 hash value of given data."""
    data_json = json_utils.DumpStr(data, sort_keys=True)
    data_hash = hashlib.sha1(data_json.encode('utf-8')).hexdigest()
    return data_hash

  def _GetPayloadDBLists(self, limit_models: Collection[str]):
    """Get payload DBs with given models and group by their boards.

    Args:
      limit_models: A set of models requiring payload generation, empty if
        unlimited.

    Returns:
      A dict in form of {board: list of database instances}
    """

    live_hwid_repo = self._hwid_repo_manager.GetLiveHWIDRepo()
    db_lists = collections.defaultdict(list)
    models = (
        limit_models
        if limit_models else set(live_hwid_repo.hwid_db_metadata_of_name))
    for model_name in models:
      try:
        hwid_action = self._hwid_action_manager.GetHWIDAction(model_name)
        db_metadata = live_hwid_repo.GetHWIDDBMetadataByName(model_name)
      except (KeyError, ValueError, RuntimeError) as ex:
        logging.error('Cannot get data for %r: %r', model_name, ex)
        continue
      db_lists[db_metadata.board_name].append(hwid_action)
    return db_lists

  def _GeneratePayloads(
      self,
      limit_models: Set[str]) -> Mapping[str, _HWIDSelectionPayloadResult]:
    """Generates payloads with given models.
    Args:
      limit_models: A set of models requiring payload generation, empty if
        unlimited.
    Returns:
      A dict in form of {board: HWID selection payload}
    """

    results = {}
    for board, hwid_actions in self._GetPayloadDBLists(limit_models).items():
      payloads = {}
      for hwid_action in hwid_actions:
        try:
          payload = hwid_action.GetFeatureMatcher().GenerateLegacyPayload()
          if payload:
            db = hwid_action.GetDBV3()
            model_name = db.project.lower()
            pathname = (f'feature-management/{model_name}/'
                        'device_selection.textproto')
            payloads[pathname] = payload
        except (KeyError, ValueError, RuntimeError) as ex:
          logging.error('Cannot get model data: %r', ex)
          continue

      if payloads:
        results[board] = _HWIDSelectionPayloadResult(payloads,
                                                     self._JsonHash(payloads))
    return results

  def _ShouldUpdatePayload(self, board: str,
                           result: _HWIDSelectionPayloadResult,
                           force_update: bool) -> bool:
    """Gets payload hash if it differs from cached hash on datastore.

    Args:
      board: Board name.
      result: Instance of `_HWIDSelectionPayloadResult`.
      force_update: True for always returning payload hash for testing purpose.

    Returns:
      A boolean which indicates if updating verification payload is needed.
    """

    if force_update:
      logging.info('Forcing update on %s as hash %s', board,
                   result.payload_hash)
      return True

    latest_hash = self._hsp_data_manager.GetLatestPayloadHash(board)
    if latest_hash == result.payload_hash:
      logging.info('%s payload is not changed as hash %s, skipped', board,
                   latest_hash)
      return False
    return True


class VerificationPayloadManager:
  """A class which manages the status of verification payloads."""

  def __init__(
      self, config_data: config_data_module.Config,
      hwid_repo_manager: hwid_repo.HWIDRepoManager,
      hwid_action_manager: hwid_action_manager_module.HWIDActionManager,
      vp_data_manager: payload_data.PayloadDataManager,
      decoder_data_manager: decoder_data_module.DecoderDataManager):

    self._config_data = config_data
    self._hwid_repo_manager = hwid_repo_manager
    self._hwid_action_manager = hwid_action_manager
    self._vp_data_manager = vp_data_manager
    self._decoder_data_manager = decoder_data_manager

  def Sync(self, force_update: bool, dryrun_upload: bool, abandon_cl: bool,
           limit_models: Set[str]):
    """Updates generated payloads to private overlays.

    This method will handle the payload creation request as follows:

      1. Check if the main commit of HWID DB is the same as cached one on
         Datastore and exit if they match.
      2. Generate a dict of board->payload_hash by vpg_module.
      3. Check if the cached payload hashes of boards in Datastore and generated
         ones match.
      4. Create a CL for each board if the generated payload hash differs from
         cached one.

    To prevent duplicate error notification or unnecessary check next time, this
    method will store the commit hash and payload hash in Datastore once
    generated.

    Args:
      force_update: Always getting payload_hash_mapping for testing purpose.
      dryrun_upload: Do everything except actually upload the CL.
      abandon_cl: Abandon created CL after uploading.
      limit_models: A set of models requiring payload generation, empty if
        unlimited.  A model will be ignored if it is not vpg-enabled.
    """

    logging.info('VerificationPayloadManager start syncing')
    hwid_main_commit = _GetHWIDMainCommitIfChanged(
        self._hwid_repo_manager, self._vp_data_manager, force_update)
    if not hwid_main_commit:
      return {}
    logging.info('VerificationPayloadManager sync with HWID commit %s',
                 hwid_main_commit)
    self._vp_data_manager.SetLatestHWIDMainCommit(hwid_main_commit)
    payload_hash_mapping = {}
    service_account_name, unused_token = git_util.GetGerritCredentials()
    author = f'chromeoshwid <{service_account_name}>'
    reviewers = self._vp_data_manager.GetCLReviewers()
    ccs = self._vp_data_manager.GetCLCCs()
    commit_msg = textwrap.dedent(f"""\
        verification payload: update payload from hwid

        From chromeos/chromeos-hwid: {hwid_main_commit}
    """)

    for board, db_list in self._GetPayloadDBLists(limit_models).items():
      setting = config_data_module.CreateVerificationPayloadSettings(board)
      result = vpg_module.GenerateVerificationPayload(db_list)
      if result.error_msgs:
        logging.error('Generate Payload fail: %s', ' '.join(result.error_msgs))
        raise PayloadGenerationException('Generate Payload fail')
      new_files = result.generated_file_contents
      if self._ShouldUpdatePayload(board, result, force_update):
        payload_hash_mapping[board] = result.payload_hash
        _TryCreateCL(dryrun_upload, abandon_cl, setting, author, reviewers, ccs,
                     new_files, commit_msg)
      self._decoder_data_manager.UpdatePrimaryIdentifiers(
          result.primary_identifiers)

    for board, payload_hash in payload_hash_mapping.items():
      self._vp_data_manager.SetLatestPayloadHash(board, payload_hash)
    logging.info('VerificationPayloadManager sync successfully')
    return payload_hash_mapping

  def _GetPayloadDBLists(self, limit_models: Set[str]):
    """Gets payload DBs specified in config.

    Args:
      limit_models: A set of models requiring payload generation, empty if
        unlimited.  A model will be ignored if it is not vpg-enabled.

    Returns:
      A dict in form of {board: list of database instances}
    """

    live_hwid_repo = self._hwid_repo_manager.GetLiveHWIDRepo()
    db_lists = collections.defaultdict(list)
    models = set(self._config_data.vpg_targets)
    if limit_models:
      models &= set(limit_models)
    for model_name in models:
      try:
        hwid_action = self._hwid_action_manager.GetHWIDAction(model_name)
        db = hwid_action.GetDBV3()
      except (KeyError, ValueError, RuntimeError) as ex:
        logging.error('Cannot get board data for %r: %r', model_name, ex)
        continue
      db_metadata = live_hwid_repo.GetHWIDDBMetadataByName(model_name)
      db_lists[db_metadata.board_name].append(
          (db, self._config_data.vpg_targets[model_name]))
    return db_lists

  def _ShouldUpdatePayload(
      self, board: str, result: vpg_module.VerificationPayloadGenerationResult,
      force_update: bool) -> bool:
    """Gets payload hash if it differs from cached hash on datastore.

    Args:
      board: Board name
      result: Instance of `VerificationPayloadGenerationResult`.
      force_update: True for always returning payload hash for testing purpose.
    Returns:
      A boolean which indicates if updating verification payload is needed.
    """

    if force_update:
      logging.info('Forcing update on %s as hash %s', board,
                   result.payload_hash)
      return True

    latest_hash = self._vp_data_manager.GetLatestPayloadHash(board)
    if latest_hash == result.payload_hash:
      logging.info('%s payload is not changed as hash %s, skipped', board,
                   latest_hash)
      return False
    return True


class SyncNameMappingRPCProvider(_HWIDIngestionProtoRPCShardBase):

  @classmethod
  def CreateInstance(cls, config):
    """Creates RPC service instance."""
    return cls(api_connector.HWIDAPIConnector(), config)

  def __init__(self, hwid_api_connector, config, *args, **kwargs):
    super().__init__(*args, **kwargs)
    self._config = config
    self.hwid_action_manager = config.hwid_action_manager
    self.decoder_data_manager = config.decoder_data_manager
    self.hwid_api_connector = hwid_api_connector
    self.hwid_data_cachers = config.hwid_data_cachers
    self._get_cid_acceptor = name_pattern_adapter.GetCIDAcceptor()

  def _ListComponentIDs(self) -> Mapping[int, Collection[str]]:
    """Lists all component IDs in HWID database.

    Returns:
      A mapping of {cid: list of projects} where HWID DB of the project contains
      the CID.
    """
    np_adapter = name_pattern_adapter.NamePatternAdapter()

    def _ResolveComponentIds(comp_cls, comps) -> Collection[int]:
      comp_ids = set()
      pattern = np_adapter.GetNamePattern(comp_cls)
      for comp_name in comps:
        name_info = pattern.Matches(comp_name)
        cid = name_info.Provide(self._get_cid_acceptor)
        if cid is not None:
          comp_ids.add(cid)
      return comp_ids

    cid_proj_mapping = collections.defaultdict(set)
    for project in self.hwid_action_manager.ListProjects():
      action = self.hwid_action_manager.GetHWIDAction(project)
      for comp_cls, comps in action.GetComponents().items():
        for cid in _ResolveComponentIds(comp_cls, comps):
          cid_proj_mapping[cid].add(project)

    return cid_proj_mapping

  @protorpc_utils.ProtoRPCServiceMethod
  @auth.RpcCheck
  def SyncNameMapping(self, request):
    """Sync name mapping from chromeos-hwid repo

    In normal circumstances the cron job triggers the refresh hourly, however it
    can be triggered by admins.  The actual work is done by the default
    background task queue.

    The task queue POSTs back into this handler to do the actual work.

    This handler will scan all component IDs in HWID DB and query HWID API to
    get AVL name mapping, then store them to datastore.
    """

    del request  # unused

    cid_proj_mapping = self._ListComponentIDs()
    comp_ids = list(cid_proj_mapping)
    avl_name_mapping = self.hwid_api_connector.GetAVLNameMapping(comp_ids)

    logging.info('Got %d AVL names from HWID API.', len(avl_name_mapping))
    touched_cids = self.decoder_data_manager.SyncAVLNameMapping(
        avl_name_mapping)
    affected_projs = set()
    for touched_cid in touched_cids:
      affected_projs.update(cid_proj_mapping[touched_cid])

    for affected_proj in affected_projs:
      logging.info(
          'Caches of HWID data of project %r is out-of-date, clear now.',
          affected_proj)
      for hwid_data_cacher in self.hwid_data_cachers:
        hwid_data_cacher.ClearCache(affected_proj)

    return ingestion_pb2.SyncNameMappingResponse()


class IngestionRPCProvider(_HWIDIngestionProtoRPCShardBase):

  @classmethod
  def CreateInstance(cls, config, config_data):
    """Creates RPC service instance."""
    return cls(config, config_data)

  def __init__(self, config, config_data, *args, **kwargs):
    super().__init__(*args, **kwargs)
    self._config = config
    self._config_data = config_data
    self.hwid_action_manager = config.hwid_action_manager
    self.vp_data_manager = config.vp_data_manager
    self.hsp_data_manager = config.hsp_data_manager
    self.hwid_db_data_manager = config.hwid_db_data_manager
    self.decoder_data_manager = config.decoder_data_manager
    self.hwid_repo_manager = config.hwid_repo_manager
    self.goldeneye_filesystem = config.goldeneye_filesystem
    self.vp_manager = VerificationPayloadManager(
        config_data, self.hwid_repo_manager, self.hwid_action_manager,
        self.vp_data_manager, self.decoder_data_manager)
    self.hsp_manager = HWIDSelectionPayloadManager(
        self.hwid_repo_manager, self.hwid_action_manager, self.hsp_data_manager)


  @protorpc_utils.ProtoRPCServiceMethod
  @auth.RpcCheck
  def IngestHwidDb(self, request):
    """Handle update of possibly new yaml files.

    In normal circumstances the cron job triggers the refresh hourly, however it
    can be triggered by admins.  The actual work is done by the default
    background task queue.

    The task queue POSTs back into this handler to do the actual work.

    Refreshing the data regularly take just over the 60 second timeout for
    interactive requests.  Using a task process extends this deadline to 10
    minutes which should be more than enough headroom for the next few years.
    """

    # Limit projects for ingestion (e2e test only).
    limit_models = set(request.limit_models)
    limit_boards = set(request.limit_boards)
    do_limit = bool(limit_models) or bool(limit_boards)
    force_push = request.force_push
    dryrun_upload = self._config_data.dryrun_upload and not force_push

    live_hwid_repo = self.hwid_repo_manager.GetLiveHWIDRepo()
    try:
      hwid_db_metadata_list = live_hwid_repo.ListHWIDDBMetadata()

      if do_limit:
        hwid_db_metadata_list = [
            x for x in hwid_db_metadata_list
            if (not limit_models or x.name in limit_models) and
            (not limit_boards or x.board_name in limit_boards)
        ]
        limit_models = set(x.name for x in hwid_db_metadata_list)

        if not hwid_db_metadata_list:
          logging.error('No model meets the limit.')
          raise protorpc_utils.ProtoRPCException(
              protorpc_utils.RPCCanonicalErrorCode.INTERNAL,
              detail='No model meets the limit.') from None

      self.hwid_db_data_manager.UpdateProjectsByRepo(
          live_hwid_repo, hwid_db_metadata_list, delete_missing=not do_limit)

    except hwid_repo.HWIDRepoError as ex:
      logging.error('Got exception from HWID repo: %r.', ex)
      raise protorpc_utils.ProtoRPCException(
          protorpc_utils.RPCCanonicalErrorCode.INTERNAL,
          detail='Got exception from HWID repo.') from None

    self.hwid_action_manager.ReloadMemcacheCacheFromFiles(
        limit_models=list(limit_models) if limit_models else None)

    # Skip if env is local (dev)
    if self._config_data.env == 'dev':
      return ingestion_pb2.IngestHwidDbResponse(msg='Skip for local env')

    response = ingestion_pb2.IngestHwidDbResponse()
    force_update = do_limit
    abandon_cl = self._config_data.env != 'prod'
    vp_payload_hash = self.vp_manager.Sync(force_update, dryrun_upload,
                                           abandon_cl, limit_models)
    hsp_payload_hash = self.hsp_manager.Sync(force_update, dryrun_upload,
                                             abandon_cl, limit_models)
    if force_update:
      # Reply payload hash (e2e test only).
      response.payload_hash.update(vp_payload_hash)
      response.hwid_selection_payload_hash.update(hsp_payload_hash)
    logging.info('Ingestion complete.')
    return response

  @protorpc_utils.ProtoRPCServiceMethod
  @auth.RpcCheck
  def IngestDevicesVariants(self, request):
    """Retrieve the file, parse and save the project to HWID regexp mapping."""
    del request  # unused

    try:
      memcache = memcache_adapter.MemcacheAdapter(
          namespace=GOLDENEYE_MEMCACHE_NAMESPACE)
      all_devices_json = self.goldeneye_filesystem.ReadFile('all_devices.json')
      parsed_json = json.loads(all_devices_json)

      regexp_to_device = []

      for device in parsed_json['devices']:
        regexp_to_project = []
        for board in device.get('boards', []):
          regexp_to_project.append(
              (board['hwid_match'], board['public_codename']))
          logging.info('Board: %s',
                       (board['hwid_match'], board['public_codename']))

        if device['hwid_match']:  # only allow non-empty patterns
          regexp_to_device.append(
              (device['hwid_match'], device['public_codename'],
               regexp_to_project))

          logging.info('Device: %s',
                       (device['hwid_match'], device['public_codename']))
        else:
          logging.warning('Empty pattern: %s',
                          (device['hwid_match'], device['public_codename']))

      memcache.Put('regexp_to_device', regexp_to_device)
    except filesystem_adapter.FileSystemAdapterException:
      logging.exception('Missing all_devices.json file during refresh.')
      raise protorpc_utils.ProtoRPCException(
          protorpc_utils.RPCCanonicalErrorCode.INTERNAL,
          detail='Missing all_devices.json file during refresh.') from None

    return ingestion_pb2.IngestDevicesVariantsResponse()
