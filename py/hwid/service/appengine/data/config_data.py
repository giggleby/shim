# Copyright 2023 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.
"""Classes for config data."""

from typing import NamedTuple, Optional

from cros.factory.hwid.service.appengine import hwid_repo


class CLSetting(NamedTuple):
  review_host: str
  repo_host: str
  project: str
  prefix: str
  branch: Optional[str]


def CreateVerificationPayloadSettings(board) -> CLSetting:
  """Create a repo setting for specific board.

  Args:
    board: The board name

  Returns:
    A CLSetting instance with corresponding settings.
  """
  return CLSetting(review_host=hwid_repo.INTERNAL_REPO_REVIEW_URL,
                   repo_host=hwid_repo.INTERNAL_REPO_URL,
                   project=f'chromeos/overlays/overlay-{board}-private',
                   prefix=f'chromeos-base/racc-config-{board}/files/',
                   branch=None)
