# Copyright 2023 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.
"""Classes for payload generation and synchronization from HWID DB."""

import abc
import collections
import hashlib
import logging
import os
import os.path
import textwrap
from typing import Collection, Mapping, NamedTuple, Optional, Sequence, Tuple, Union

from cros.factory.hwid.service.appengine.data import config_data as config_data_module
from cros.factory.hwid.service.appengine.data import decoder_data as decoder_data_module
from cros.factory.hwid.service.appengine.data import payload_data
from cros.factory.hwid.service.appengine import feature_matching
from cros.factory.hwid.service.appengine import git_util
from cros.factory.hwid.service.appengine import hwid_action_manager as hwid_action_manager_module
from cros.factory.hwid.service.appengine import hwid_repo
from cros.factory.hwid.service.appengine import verification_payload_generator as vpg_module
from cros.factory.probe_info_service.app_engine import protorpc_utils
from cros.factory.utils import json_utils


class _Payload(NamedTuple):
  """Holds data generated by PayloadManager._GeneratePayloads().

  Attributes:
    contents: The generated payload contents in form of a dictionary mapping
      file names to content.
    hash_value: The hash value of contents.
    metadata: Additional payload metadata.
  """
  contents: Mapping[str, str]
  hash_value: str
  # TODO(kevinptt): Make metadata typeable.
  metadata: dict


class UpdatedResult(NamedTuple):
  """A holder of result."""
  payload_hash: str
  change_id: str


def _JSONHash(data) -> str:
  """Calculates the SHA1 hash value of given data."""
  data_json = json_utils.DumpStr(data, sort_keys=True)
  data_hash = hashlib.sha1(data_json.encode('utf-8')).hexdigest()
  return data_hash


class PayloadGenerationException(protorpc_utils.ProtoRPCException):
  """Exception to group similar exceptions for error reporting."""

  def __init__(self, msg):
    super().__init__(protorpc_utils.RPCCanonicalErrorCode.INTERNAL, detail=msg)


class PayloadManager(abc.ABC):
  """A base class managing payloads generated from HWID DB."""

  def __init__(
      self, data_manager: payload_data.PayloadDataManager,
      hwid_action_manager: hwid_action_manager_module.HWIDActionManager,
      config_data: config_data_module.Config):

    self._logger = logging.getLogger(self.__class__.__name__)
    self._data_manager = data_manager
    self._hwid_action_manager = hwid_action_manager
    self._config_data = config_data
    self._gerrit_credentials = None
    self._auth_cookie = None

  @property
  def _author(self) -> str:
    service_account_name = self._gerrit_credentials[0]
    return f'chromeoshwid <{service_account_name}>'

  def _RefreshCredential(self):
    self._gerrit_credentials = git_util.GetGerritCredentials()
    self._auth_cookie = git_util.GetGerritAuthCookie(self._gerrit_credentials)

  def _ShouldUpdatePayload(self, board: str, payloads: _Payload,
                           force_update: bool) -> bool:
    if force_update:
      self._logger.info('Forcing update on %s as hash %s', board,
                        payloads.hash_value)
      return True

    latest_hash = self._data_manager.GetLatestPayloadHash(board)
    if latest_hash == payloads.hash_value:
      self._logger.info('%s payload is not changed as hash %s, skipped', board,
                        latest_hash)
      return False
    return True

  @abc.abstractmethod
  def _GetSupportedModels(
      self, limit_models: Collection[str],
      live_hwid_repo: hwid_repo.HWIDRepo) -> Mapping[str, Collection[str]]:
    """Returns models supported by the generator.

    Args:
      limit_models: See Update().
      live_hwid_repo: See Update().

    Returns:
      A dict that maps board names to list of model names.
    """

  @abc.abstractmethod
  def _GeneratePayloads(self, board: str,
                        models: Collection[str]) -> Optional[_Payload]:
    """Generates payloads.

    Args:
      board: Board name.
      models: Model names.

    Returns:
      A generated payload instance.
      This will be None if no payloads are generated.
    """

  @abc.abstractmethod
  def _GetCLSetting(self, board: str) -> config_data_module.CLSetting:
    """Returns repository settings."""

  @abc.abstractmethod
  def _GetCLMessage(self, board: str, models: Collection[str],
                    payload: _Payload, hwid_commit: str,
                    hwid_prev_commit: str) -> str:
    """Returns the CL message."""

  @abc.abstractmethod
  def _PostUpdate(self, board: str, models: Collection[str], change_id: str,
                  payload: _Payload):
    """Runs additional operations after the CL is created.

    Override this function to run additional operations after the CL is created,
    such as updating datastore.

    Args:
      board: Board name.
      models: Model names.
      change_id: The CL change ID.
      payload: The payloads generated by _GeneratePayloads().
    """

  def Update(self, dryrun: bool, limit_models: Collection[str],
             force_update: bool,
             live_hwid_repo: hwid_repo.HWIDRepo) -> Mapping[str, UpdatedResult]:
    """Updates payload with the HWID DB.

    Args:
      dryrun: Do everything except actually upload the CL.
      limit_models: A set of models requiring payload generation, empty if
        unlimited.
      force_update: Generate payload change CLs without checking payload hash in
        advance.
      live_hwid_repo: A HWIDRepo instance being processed.

    Returns:
      A dict mapping board names to its updated results.
    """
    self._logger.info('Start syncing')
    config = self._data_manager.config
    if config.disabled and not force_update:
      self._logger.info('The payload generator is disabled, skipped')
      return {}

    hwid_live_commit = live_hwid_repo.hwid_db_commit_id
    hwid_prev_commit = self._data_manager.GetLatestHWIDMainCommit()
    if hwid_prev_commit == hwid_live_commit and not force_update:
      self._logger.info('The HWID live commit %s is already processed, skipped',
                        hwid_live_commit)
      return {}
    self._logger.info('Sync with HWID commit %s', hwid_live_commit)

    result = {}
    self._RefreshCredential()
    author = self._author
    if config.approval_method == payload_data.ApprovalMethod.BOT:
      if not self._config_data.payload_bot_reviewer:
        self._logger.warning('"payload_bot_reviewer" config is empty')
      reviewers = [self._config_data.payload_bot_reviewer]
      ccs = config.reviewers + config.ccs
      self_approval = False
    elif config.approval_method == payload_data.ApprovalMethod.SELF:
      reviewers = []
      ccs = config.reviewers + config.ccs
      self_approval = True
    elif config.approval_method == payload_data.ApprovalMethod.MANUAL:
      reviewers = config.reviewers
      ccs = config.ccs
      self_approval = False
    else:
      raise ValueError('Invalid approval_method: ', config.approval_method)
    for board, models in self._GetSupportedModels(limit_models,
                                                  live_hwid_repo).items():
      payloads = self._GeneratePayloads(board, models)
      if payloads is not None and self._ShouldUpdatePayload(
          board, payloads, force_update):
        setting = self._GetCLSetting(board)
        git_url = f'{setting.repo_host}/{setting.project}'
        branch = setting.branch or git_util.GetCurrentBranch(
            setting.review_host, setting.project, self._auth_cookie)
        git_files = [(os.path.join(
            setting.prefix, filepath), git_util.NORMAL_FILE_MODE, filecontent)
                     for filepath, filecontent in payloads.contents.items()]
        commit_msg = self._GetCLMessage(board, models, payloads,
                                        hwid_live_commit, hwid_prev_commit)
        try:
          change_id, unused_cl_number = self._CreateCL(
              dryrun, git_url, self._auth_cookie, branch, git_files, author,
              author, commit_msg, reviewers, ccs, topic=setting.topic,
              bot_commit=self_approval, commit_queue=self_approval,
              auto_submit=True, hashtags=setting.hashtags)
          self._PostUpdate(board, models, change_id, payloads)
          result[board] = UpdatedResult(payloads.hash_value, change_id)
        except git_util.GitUtilNoModificationException:
          self._logger.debug('No modification is made, skipped')
        except git_util.GitUtilException as ex:
          self._logger.error('CL is not created: %r', str(ex))
          raise PayloadGenerationException('CL is not created') from ex

    self._data_manager.SetLatestHWIDMainCommit(hwid_live_commit)
    self._logger.info('Sync successfully to %s.', hwid_live_commit)
    return result

  def AbandonCLs(self, dryrun: bool, change_ids: Mapping[str, str]):
    """Abandons CLs with given change IDs."""
    for board, change_id in change_ids.items():
      setting = self._GetCLSetting(board)
      try:
        self._AbandonCL(dryrun, setting.review_host, self._auth_cookie,
                        change_id)
      except git_util.GitUtilException as ex:
        self._logger.error('Cannot abandon CL for %r: %r', change_id, str(ex))

  def _CreateCL(
      self,
      dryrun: bool,
      git_url: str,
      auth_cookie: str,
      branch: str,
      new_files: Sequence[Tuple[str, int, Union[str, bytes]]],
      author: str,
      committer: str,
      commit_msg: str,
      reviewers: Optional[Sequence[str]] = None,
      cc: Optional[Sequence[str]] = None,
      bot_commit: bool = False,
      commit_queue: bool = False,
      repo: Optional[git_util.MemoryRepo] = None,
      topic: Optional[str] = None,
      verified: int = 0,
      auto_submit: bool = False,
      rubber_stamper: bool = False,
      hashtags: Optional[Sequence[str]] = None,
  ) -> Tuple[Optional[str], Optional[int]]:
    """Creates a CL with given options.

    See git_util.CreateCL() for descriptions of other arguments.

    Args:
      dryrun: Do everything except actually upload the CL.

    Returns:
      A tuple of (change ID, CL number).
      Both will be None if the CL is not created.

    Raises:
      See git_util.CreateCL().
    """
    if dryrun:
      # file_info = (file_path, mode, content)
      file_paths = '\n'.join('  ' + file_info[0] for file_info in new_files)
      debug_info = textwrap.dedent(f"""\
          Dryrun create
          git_url: {git_url}
          branch: {branch}
          author: {author}
          reviewers: {reviewers}
          cc: {cc}
          bot_commit: {bot_commit}
          commit_queue: {commit_queue}
          auto_submit: {auto_submit}
          commit msg: \n{textwrap.indent(commit_msg, '          ')}
          update file paths: \n{textwrap.indent(file_paths, '          ')}
      """)
      self._logger.debug(debug_info)
      return None, None
    return git_util.CreateCL(git_url, auth_cookie, branch, new_files, author,
                             committer, commit_msg, reviewers, cc, bot_commit,
                             commit_queue, repo, topic, verified, auto_submit,
                             rubber_stamper, hashtags)

  def _AbandonCL(self, dryrun: bool, review_host: str, auth_cookie, change_id,
                 reason: Optional[str] = None):
    """Abandons a CL.

    See git_util.AbandonCL() for descriptions of other arguments.

    Args:
      dryrun: Do everything except actually upload the CL.

    Raises:
      See git_util.AbandonCL().
    """
    if dryrun:
      debug_info = textwrap.dedent(f"""\
          Dryrun abandon
          review_host: {review_host}
          change_id: {change_id}
      """)
      self._logger.debug(debug_info)
      return

    git_util.Abandon(review_host, auth_cookie, change_id, reason)


class HWIDSelectionPayloadManager(PayloadManager):
  """A class managing payloads for HWID selection generated from HWID DB."""

  def _GetSupportedModels(
      self, limit_models: Collection[str],
      live_hwid_repo: hwid_repo.HWIDRepo) -> Mapping[str, Collection[str]]:
    """See base class."""
    board_models = collections.defaultdict(list)
    models = (
        limit_models
        if limit_models else set(live_hwid_repo.hwid_db_metadata_of_name))
    for model_name in models:
      try:
        db_metadata = live_hwid_repo.GetHWIDDBMetadataByName(model_name)
      except (KeyError, ValueError, RuntimeError) as ex:
        self._logger.error('Cannot get board data for %r: %r', model_name, ex)
        continue
      board_models[db_metadata.board_name].append(model_name)
    return board_models

  def _GeneratePayloads(self, board: str,
                        models: Collection[str]) -> Optional[_Payload]:
    """See base class."""
    payload_builder = feature_matching.LegacyPayloadBuilder()
    generated_models = []
    for model in sorted(models):
      try:
        hwid_action = self._hwid_action_manager.GetHWIDAction(model)
        selection = hwid_action.GetFeatureMatcher().GenerateLegacyPayload()
        if selection is None:
          continue
        generated_models.append(model)
        payload_builder.AppendDeviceSelection(selection)
      except (KeyError, ValueError, RuntimeError) as ex:
        self._logger.error('Cannot get model data: %r', ex)
        continue
    payload_msg = payload_builder.Build()
    if payload_msg is None:
      return None
    payloads = {
        'device_selection.textproto': payload_msg
    }
    return _Payload(payloads, _JSONHash(payloads), {'models': generated_models})

  def _GetCLSetting(self, board: str) -> config_data_module.CLSetting:
    """See base class."""
    return config_data_module.CreateHWIDSelectionPayloadSettings(board)

  def _GetCLMessage(self, board: str, models: Collection[str],
                    payload: _Payload, hwid_commit: str,
                    hwid_prev_commit: Optional[str]) -> str:
    """See base class."""

    generated_models = (
        payload.metadata['models'] if 'models' in payload.metadata else models)
    feature_matcher_paths = [
        f'v3/{model.upper()}.feature_matcher.textproto'
        for model in sorted(generated_models)
    ]
    if hwid_prev_commit is None:
      feature_matcher_file_objects = [
          f'{hwid_commit[:7]}:{path}' for path in feature_matcher_paths
      ]
      verification_command = (
          'git show \\\n' +
          textwrap.indent(' \\\n'.join(feature_matcher_file_objects), '  '))
    else:
      verification_command = (
          f'git diff {hwid_prev_commit[:7]}..{hwid_commit[:7]} -- \\\n' +
          textwrap.indent(' \\\n'.join(feature_matcher_paths), '  '))
    return textwrap.dedent(f"""\
        feature-management-bsp: update payload from hwid

        From chromeos/chromeos-hwid: {hwid_commit}

        This CL is driven by the following HWID repository update:
    """) + textwrap.indent(verification_command, '  ')

  def _PostUpdate(self, board: str, models: Collection[str], change_id: str,
                  payload: _Payload):
    self._data_manager.SetLatestPayloadHash(board, payload.hash_value)


class VerificationPayloadManager(PayloadManager):
  """A class managing payloads for AVL verification generated from HWID DB."""

  def __init__(
      self, data_manager: payload_data.PayloadDataManager,
      hwid_action_manager: hwid_action_manager_module.HWIDActionManager,
      config_data: config_data_module.Config,
      decoder_data_manager: decoder_data_module.DecoderDataManager):

    super().__init__(data_manager, hwid_action_manager, config_data)
    self._decoder_data_manager = decoder_data_manager

  def _GetSupportedModels(
      self, limit_models: Collection[str],
      live_hwid_repo: hwid_repo.HWIDRepo) -> Mapping[str, Collection[str]]:
    """See base class."""
    board_models = collections.defaultdict(list)
    models = set(self._config_data.vpg_targets)
    if limit_models:
      models &= set(limit_models)
    for model_name in models:
      try:
        db_metadata = live_hwid_repo.GetHWIDDBMetadataByName(model_name)
      except (KeyError, ValueError, RuntimeError) as ex:
        self._logger.error('Cannot get board data for %r: %r', model_name, ex)
        continue
      board_models[db_metadata.board_name].append(model_name)
    return board_models

  def _GeneratePayloads(self, board: str,
                        models: Collection[str]) -> Optional[_Payload]:
    """See base class."""
    db_list = []
    for model in models:
      try:
        hwid_action = self._hwid_action_manager.GetHWIDAction(model)
        db = hwid_action.GetDBV3()
      except (KeyError, ValueError, RuntimeError) as ex:
        self._logger.error('Cannot get model data: %r', ex)
      db_list.append((db, self._config_data.vpg_targets[model]))
    result = vpg_module.GenerateVerificationPayload(db_list)
    return _Payload(result.generated_file_contents, result.payload_hash,
                    {'primary_identifier': result.primary_identifiers})

  def _GetCLSetting(self, board: str) -> config_data_module.CLSetting:
    """See base class."""
    return config_data_module.CreateVerificationPayloadSettings(board)

  def _GetCLMessage(self, board: str, models: Collection[str],
                    payload: _Payload, hwid_commit: str,
                    hwid_prev_commit: str) -> str:
    """See base class."""
    return textwrap.dedent(f"""\
        verification payload: update payload from hwid

        From chromeos/chromeos-hwid: {hwid_commit}
    """)

  def _PostUpdate(self, board: str, models: Collection[str], change_id: str,
                  payload: _Payload):
    """See base class."""
    self._data_manager.SetLatestPayloadHash(board, payload.hash_value)
    if 'primary_identifier' in payload.metadata:
      self._decoder_data_manager.UpdatePrimaryIdentifiers(
          payload.metadata['primary_identifier'])
