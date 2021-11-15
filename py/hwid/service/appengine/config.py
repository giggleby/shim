# Copyright 2018 The Chromium OS Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.
"""Cloud stoarge buckets and service environment configuration."""

import collections
import os
from typing import NamedTuple, Optional

import yaml

from cros.factory.hwid.service.appengine import cloudstorage_adapter
from cros.factory.hwid.service.appengine.data import decoder_data
from cros.factory.hwid.service.appengine.data import hwid_db_data
from cros.factory.hwid.service.appengine.data import verification_payload_data
from cros.factory.hwid.service.appengine import hwid_manager
from cros.factory.hwid.service.appengine import hwid_repo
from cros.factory.hwid.service.appengine import ndb_connector as ndbc_module
from cros.factory.utils import file_utils
from cros.factory.utils import type_utils


_DEFAULT_CONFIGURATION = {
    'env': 'dev',
    'bucket': 'chromeoshwid-dev',
    # Allow unauthenticated access when running a local dev server and
    # during tests.
    'ge_bucket': 'chromeos-build-release-console-staging',
    'vpg_targets': {
        'SARIEN': {  # for unittests
            'board': 'sarien',
            'waived_comp_categories': ['ethernet']
        }
    },
    'hwid_repo_branch': 'no_such_branch',
    'project_region': '',
    'queue_name': ''
}

_RESOURCE_DIR = os.path.join(
    os.path.dirname(os.path.realpath(__file__)), '..', '..', '..', '..', '..',
    'resource')

_PATH_TO_APP_CONFIGURATIONS_FILE = os.path.join(_RESOURCE_DIR,
                                                'configurations.yaml')

_VerificationPayloadGenerationTargetInfo = collections.namedtuple(
    '_VerificationPayloadGenerationTargetInfo',
    ['board', 'waived_comp_categories'])


class VerificationPayloadSettings(NamedTuple):
  review_host: str
  repo_host: str
  repo_path: str
  project: str
  prefix: str
  branch: Optional[str]


class _Config:
  """Config for AppEngine environment.

  Attributes:
    env: A string for the environment.
    goldeneye_filesystem: A FileSystemAdapter object, the GoldenEye filesystem
        on CloudStorage.
    hwid_filesystem: A FileSystemAdapter object, the HWID filesystem on
        CloudStorage.
    hwid_manager: A HwidManager object. HwidManager manipulates HWIDs in
        hwid_filesystem.
    hwid_repo_manager: A HWIDRepoManager object, which provides functionalities
        to manipulate the HWID repository.
  """

  def __init__(self, config_path=_PATH_TO_APP_CONFIGURATIONS_FILE):
    super(_Config, self).__init__()
    self.cloud_project = os.environ.get('GOOGLE_CLOUD_PROJECT')
    self.gae_env = os.environ.get('GAE_ENV')
    try:
      confs = yaml.load(file_utils.ReadFile(config_path))
      conf = confs[self.cloud_project]
    except (KeyError, OSError, IOError):
      conf = _DEFAULT_CONFIGURATION

    self.env = conf['env']
    self.goldeneye_filesystem = cloudstorage_adapter.CloudStorageAdapter(
        conf['ge_bucket'])
    self.hwid_filesystem = cloudstorage_adapter.CloudStorageAdapter(
        conf['bucket'])
    self.vpg_targets = {
        k: _VerificationPayloadGenerationTargetInfo(
            v['board'], v.get('waived_comp_categories', []))
        for k, v in conf.get('vpg_targets', {}).items()
    }
    self._ndb_connector = ndbc_module.NDBConnector()
    self.vp_data_manager = (
        verification_payload_data.VerificationPayloadDataManager(
            self._ndb_connector))
    self.decoder_data_manager = decoder_data.DecoderDataManager(
        self._ndb_connector)
    self.hwid_db_data_manager = hwid_db_data.HWIDDBDataManager(
        self._ndb_connector, self.hwid_filesystem)
    self.hwid_manager = hwid_manager.HwidManager(self.vpg_targets,
                                                 self.hwid_db_data_manager)
    self.dryrun_upload = conf.get('dryrun_upload', True)
    self.project_region = conf['project_region']
    self.queue_name = conf['queue_name']
    # Setting this config empty means the branch HEAD tracks.
    self.hwid_repo_branch = conf['hwid_repo_branch']
    self.client_allowlist = conf.get('client_allowlist', [])
    self.hwid_repo_manager = hwid_repo.HWIDRepoManager(self.hwid_repo_branch)

  def GetVerificationPayloadSettings(self, board):
    """Get repo settings for specific board.

    Args:
      board: The board name

    Returns:
      A dictionary with corresponding settings
    """
    return VerificationPayloadSettings(
        review_host='https://chrome-internal-review.googlesource.com',
        repo_host='https://chrome-internal.googlesource.com',
        repo_path=f'/chromeos/overlays/overlay-{board}-private',
        project=f'chromeos/overlays/overlay-{board}-private',
        prefix=f'chromeos-base/racc-config-{board}/files/', branch=None)


CONFIG = type_utils.LazyObject(_Config)
