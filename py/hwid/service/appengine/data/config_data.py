# Copyright 2023 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.
"""Classes for config data."""

from typing import NamedTuple, Optional, Sequence

from cros.factory.hwid.service.appengine import hwid_repo


class CLSetting(NamedTuple):
  review_host: str
  repo_host: str
  project: str
  prefix: str
  branch: Optional[str]


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


def CreateVerificationPayloadSettings(board) -> CLSetting:
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
                   branch=None)
