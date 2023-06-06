# Copyright 2018 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.
"""Cloud stoarge buckets and service environment configuration."""

import yaml

from cros.factory.hwid.service.appengine import cloudstorage_adapter
from cros.factory.hwid.service.appengine.data import avl_metadata_util
from cros.factory.hwid.service.appengine.data import config_data
from cros.factory.hwid.service.appengine.data.converter import converter_utils
from cros.factory.hwid.service.appengine.data import decoder_data
from cros.factory.hwid.service.appengine.data import hwid_db_data
from cros.factory.hwid.service.appengine.data import payload_data
from cros.factory.hwid.service.appengine import hwid_action_manager
from cros.factory.hwid.service.appengine.hwid_api_helpers import bom_and_configless_helper as bc_helper_module
from cros.factory.hwid.service.appengine import hwid_repo
from cros.factory.hwid.service.appengine import memcache_adapter
from cros.factory.hwid.service.appengine import ndb_connector as ndbc_module
from cros.factory.utils import file_utils
from cros.factory.utils import type_utils


_CONFIG_DATA = config_data.CONFIG
HWID_PREPROC_DATA_MEMCACHE_NAMESPACE = 'HWIDObject'
BOM_DATA_MEMCACHE_NAMESPACE = 'BOMAndConfigless'


class _Config:
  """Config for AppEngine environment.

  Attributes:
    goldeneye_filesystem: An IFileSystemAdapter object, the GoldenEye filesystem
        on CloudStorage.
    hwid_filesystem: An IFileSystemAdapter object, the HWID filesystem on
        CloudStorage.
    vp_data_manager: A VerificationPayloadDataManager instance responsible for
        reading/writing payload related metadata.
    decoder_data_manager: A DecoderDataManager instance responsible for
        reading/writing decode-related configs (e.g. AVL names from DLM and
        PrimaryIdentifier).
    hwid_db_data_manager: A HWIDDBDataManager instance responsible for
        reading/writing HWID DB data/metadata.
    bom_data_cacher: A BOMDataCacher instance responsible for cache responses of
        BOM related APIs.
    hwid_action_manager: A HWIDActionManager object. The object maintains
        HWIDAction objects, which provide HWID DB related operations.
    hwid_repo_manager: A HWIDRepoManager object, which provides functionalities
        to manipulate the HWID repository.
    avl_converter_manager: A ConverterManager instance responsible for
        converting probe info from AVL and matching the probed value in HWID DB.
    avl_metadata_manager: A AVLMetadataManager instance responsible for
        collecting/uploading AVL related attrs for customized the validation
        process.
  """

  def __init__(self, config_path=config_data.PATH_TO_APP_CONFIGURATIONS_FILE):
    try:
      confs = yaml.safe_load(file_utils.ReadFile(config_path))
      conf = confs[_CONFIG_DATA.cloud_project or 'local']
    except (KeyError, OSError, IOError):
      conf = config_data.DEFAULT_CONFIGURATION

    self.goldeneye_filesystem = cloudstorage_adapter.CloudStorageAdapter(
        conf['ge_bucket'])
    self.hwid_filesystem = cloudstorage_adapter.CloudStorageAdapter(
        conf['bucket'])
    ndb_connector = ndbc_module.NDBConnector()
    self.vp_data_manager = (
        payload_data.PayloadDataManager(ndb_connector,
                                        payload_data.PayloadType.VERIFICATION))
    self.decoder_data_manager = decoder_data.DecoderDataManager(ndb_connector)
    self.hwid_db_data_manager = hwid_db_data.HWIDDBDataManager(
        ndb_connector, self.hwid_filesystem)
    hwid_preproc_data_memcache_adapter = memcache_adapter.MemcacheAdapter(
        namespace=HWID_PREPROC_DATA_MEMCACHE_NAMESPACE)
    bom_data_memcache_adapter = memcache_adapter.MemcacheAdapter(
        namespace=BOM_DATA_MEMCACHE_NAMESPACE)
    self.bom_data_cacher = bc_helper_module.BOMDataCacher(
        bom_data_memcache_adapter)
    self.hwid_data_cachers = [self.bom_data_cacher]
    self.hwid_action_manager = hwid_action_manager.HWIDActionManager(
        self.hwid_db_data_manager,
        hwid_preproc_data_memcache_adapter,
        self.hwid_data_cachers,
    )
    self.hwid_repo_manager = hwid_repo.HWIDRepoManager(
        _CONFIG_DATA.hwid_repo_branch,
        _CONFIG_DATA.unverified_cl_ccs,
    )
    self.avl_converter_manager = converter_utils.ConverterManager.FromDefault()

    avl_metadata_setting = conf.get('avl_metadata_setting', {})
    secret_var_namespace = avl_metadata_setting.get('secret_var_namespace', '')
    avl_metadata_topic = avl_metadata_setting.get('topic', '')
    avl_metadata_cl_ccs = avl_metadata_setting.get('cl_ccs', [])
    self.avl_metadata_manager = avl_metadata_util.AVLMetadataManager(
        ndb_connector,
        config_data.AVLMetadataSetting.CreateInstance(
            _CONFIG_DATA.dryrun_upload,
            secret_var_namespace,
            avl_metadata_topic,
            avl_metadata_cl_ccs,
        ))


CONFIG = type_utils.LazyObject(_Config)
