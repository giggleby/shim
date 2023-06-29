# Copyright 2023 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.
"""Classes for config data and the data-only config singleton."""

import os
from typing import NamedTuple, Optional, Sequence

import yaml

from cros.factory.hwid.service.appengine import hwid_repo
from cros.factory.hwid.service.appengine import verification_payload_generator_config as vpg_config_module
from cros.factory.utils import file_utils
from cros.factory.utils import type_utils


DEFAULT_CONFIGURATION = {
    'env': 'dev',
    'bucket': 'chromeoshwid-staging',
    # Allow unauthenticated access when running a local dev server and
    # during tests.
    'ge_bucket': 'chromeos-build-release-console-staging',
    'vpg_targets': {
        'SARIEN': {  # for unittests
            'waived_comp_categories': ['ethernet']
        }
    },
    'hwid_repo_branch': 'stabilize-15251.B',
    'project_region': '',
    'queue_name': '',
    'hwid_api_endpoint': ''
}

_RESOURCE_DIR = os.path.join(
    os.path.dirname(os.path.realpath(__file__)), '..', '..', '..', '..', '..',
    '..', 'resource')

PATH_TO_APP_CONFIGURATIONS_FILE = os.path.join(_RESOURCE_DIR,
                                               'configurations.yaml')


class CLSetting(NamedTuple):
  review_host: str
  repo_host: str
  project: str
  prefix: str
  branch: Optional[str] = None
  topic: Optional[str] = None
  hashtags: Optional[Sequence[str]] = None


class AVLMetadataSetting(NamedTuple):
  dryrun_upload: bool
  cl_setting: CLSetting
  secret_var_namespace: str
  avl_metadata_topic: str
  avl_metadata_cl_ccs: Optional[Sequence[str]] = None

  @classmethod
  def CreateInstance(
      cls, dryrun_upload: bool, secret_var_namespace: str,
      avl_metadata_topic: str,
      avl_metadata_cl_ccs: Optional[Sequence[str]]) -> 'AVLMetadataSetting':
    """Creates a setting of AVLMetadata for creating new CLs.

    Args:
      dryrun_upload: True if no CL will be created.
      avl_metadata_topic: A str of topic set to the created CL.
      avl_metadata_cl_ccs: An optional list of CCs set to the created CL.

    Returns:
      A AVLMetadataSetting instance with corresponding settings.
    """
    return cls(
        dryrun_upload=dryrun_upload,
        cl_setting=CLSetting(review_host=hwid_repo.INTERNAL_REPO_REVIEW_URL,
                             repo_host=hwid_repo.INTERNAL_REPO_URL,
                             project='chromeos/platform/tast-tests-private',
                             prefix='vars/', branch=None),
        secret_var_namespace=secret_var_namespace,
        avl_metadata_topic=avl_metadata_topic,
        avl_metadata_cl_ccs=avl_metadata_cl_ccs,
    )


def CreateVerificationPayloadSettings(board: str) -> CLSetting:
  """Create a repo setting for specific board.

  Args:
    board: The board name

  Returns:
    A CLSetting instance with corresponding settings.
  """
  return CLSetting(review_host=hwid_repo.INTERNAL_REPO_REVIEW_URL,
                   repo_host=hwid_repo.INTERNAL_REPO_URL,
                   project=f'chromeos/overlays/overlay-{board.lower()}-private',
                   prefix=f'chromeos-base/racc-config-{board.lower()}/files/',
                   branch=None,
                   topic='racc-verification-payload-automated-sync',
                   hashtags=[f'racc-verification-payload-{board.lower()}'])

def CreateHWIDSelectionPayloadSettings(board: str) -> CLSetting:
  """Create a repo setting of HWID selection payload for specific board.

  Args:
    board: The board name

  Returns:
    A CLSetting instance with corresponding settings.
  """
  return CLSetting(review_host=hwid_repo.INTERNAL_REPO_REVIEW_URL,
                   repo_host=hwid_repo.INTERNAL_REPO_URL,
                   project=f'chromeos/overlays/overlay-{board.lower()}-private',
                   prefix='chromeos-base/feature-management-bsp/files/',
                   branch=None, topic='hwid-selection-payload-automated-sync',
                   hashtags=[f'hwid-selection-payload-{board.lower()}'])


class Config:
  """Config for AppEngine environment.

  Attributes:
    cloud_project: The cloud project of the service.
    env: The deployment environment.
    vpg_targets: A mapping of {project: VerificationPayloadGeneratorConfig}
        specifying the customization of the payload generation.
    dryrun_upload: A bool indicating whether the CL upload process is dryrun (
        just logging without actually create one) or not.
    project_region: The project region used in cloud tasks.
    queue_name: The queue name used in cloud tasks.
    hwid_repo_branch: The branch of HWID repo used in this service.
    unverified_cl_ccs: The emails which will be CC'd when there is an
        unverificed CL created.
    client_allowlist: The accounts who have permission to directly make stubby
        calls to the service.
    hwid_api_endpoint: The endpoint of HWID API.
  """

  def __init__(self, config_path=PATH_TO_APP_CONFIGURATIONS_FILE):
    self.cloud_project = os.environ.get('GOOGLE_CLOUD_PROJECT')
    try:
      confs = yaml.safe_load(file_utils.ReadFile(config_path))
      conf = confs[self.cloud_project or 'local']
    except (KeyError, OSError, IOError):
      conf = DEFAULT_CONFIGURATION

    self.env = conf['env']
    self.vpg_targets = (
        vpg_config_module.VerificationPayloadGeneratorConfig.BatchCreate(
            conf.get('vpg_targets', {})))
    self.dryrun_upload = conf.get('dryrun_upload', True)
    self.project_region = conf['project_region']
    self.queue_name = conf['queue_name']
    # Setting this config empty means the branch HEAD tracks.
    self.hwid_repo_branch = conf['hwid_repo_branch']
    self.unverified_cl_ccs = conf.get('unverified_cl_ccs', [])
    self.client_allowlist = conf.get('client_allowlist', [])
    self.hwid_api_endpoint = conf['hwid_api_endpoint']
    self.cq_count_over_limit_cl_reviewers = conf.get(
        'cq_count_over_limit_cl_reviewers', [])


CONFIG = type_utils.LazyObject(Config)
