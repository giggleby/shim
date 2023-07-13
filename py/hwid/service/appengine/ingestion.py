# Copyright 2018 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.
"""Handler for ingestion."""

import collections
import json
import logging
from typing import Collection, Mapping

from cros.factory.hwid.service.appengine import api_connector
from cros.factory.hwid.service.appengine import auth
from cros.factory.hwid.service.appengine import hwid_repo
from cros.factory.hwid.service.appengine import memcache_adapter
from cros.factory.hwid.service.appengine import payload_management
from cros.factory.hwid.service.appengine.proto import ingestion_pb2  # pylint: disable=no-name-in-module
from cros.factory.hwid.v3 import filesystem_adapter
from cros.factory.hwid.v3 import name_pattern_adapter
from cros.factory.probe_info_service.app_engine import protorpc_utils


GOLDENEYE_MEMCACHE_NAMESPACE = 'SourceGoldenEye'


_HWIDIngestionProtoRPCShardBase = protorpc_utils.CreateProtoRPCServiceShardBase(
    'HwidIngestionProtoRPCShardBase',
    ingestion_pb2.DESCRIPTOR.services_by_name['HwidIngestion'])


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
    self.hwid_db_data_manager = config.hwid_db_data_manager
    self.decoder_data_manager = config.decoder_data_manager
    self.hwid_repo_manager = config.hwid_repo_manager
    self.goldeneye_filesystem = config.goldeneye_filesystem
    self.vp_manager = payload_management.VerificationPayloadManager(
        config.vp_data_manager, self.hwid_repo_manager,
        self.hwid_action_manager, config_data, self.decoder_data_manager)
    self.hsp_manager = payload_management.HWIDSelectionPayloadManager(
        config.hsp_data_manager, self.hwid_repo_manager,
        self.hwid_action_manager)

  def _UpdatePayloads(self, payload_manager: payload_management.PayloadManager,
                      dryrun: bool, limit_models: bool,
                      force_update: bool) -> Mapping[str, str]:
    board_result = payload_manager.Update(dryrun, limit_models, force_update)
    change_ids = {
        board: result.change_id
        for board, result in board_result.items()
    }
    if self._config_data.env != 'prod':
      payload_manager.AbandonCLs(dryrun, change_ids)
    return {
        board: result.payload_hash
        for board, result in board_result.items()
    }

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
    vp_payload_hash = self._UpdatePayloads(self.vp_manager, dryrun_upload,
                                           limit_models, force_update)
    hsp_payload_hash = self._UpdatePayloads(self.hsp_manager, dryrun_upload,
                                            limit_models, force_update)
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
