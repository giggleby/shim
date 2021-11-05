# Copyright 2021 The Chromium OS Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.
"""Check if release image has enabled LVM stateful partition.

Description
-----------
This test checks whether Chrome OS release image has enabled LVM stateful
partition. The test fails if it has not enabled.

To run the check with shell script::

  #!/bin/sh

  root_dev="$(rootdev -s -d)"
  release_dev="${root_dev}p5"
  mount_pnt="$(mktemp -d)"
  chromeos_startup_path="${mount_pnt}"/sbin/chromeos_startup

  mount -o ro "${release_dev}" "${mount_pnt}"
  if grep -q 'USE_LVM_STATEFUL_PARTITION=1' "${chromeos_startup_path}"; then
    echo "Release image uses LVM stateful partition!"
  else
    echo "Release image uses EXT4 stateful partition!"
  fi

  umount "${mount_pnt}"
  rmdir "${mount_pnt}"

To run the check with gooftool::

  gooftool get_release_fs_type

Test Procedure
--------------
1. Mount the release rootfs.
2. Grep the flag `USE_LVM_STATEFUL_PARTITION` from
   `mount_point/sbin/chromeos_startup`.
3. Check if step 2 returns `True`.

Dependency
----------
`grep`

Examples
--------
To check if release image has enabled LVM stateful partition, add this to test
list::

  {
    "pytest_name": "check_release_lvm_stateful"
  }
"""

import logging

from cros.factory.gooftool.common import Util
from cros.factory.test import test_case
from cros.factory.test import test_ui
from cros.factory.utils import sys_utils


class CheckImageVersionTest(test_case.TestCase):

  ui_class = test_ui.ScrollableLogUI

  def runTest(self):
    logging.info('Mount release rootfs to check the LVM flag...')
    release_rootfs = Util().GetReleaseRootPartitionPath()
    with sys_utils.MountPartition(release_rootfs) as root:
      self.assertTrue(
          Util().UseLVMStatefulPartition(root),
          'Please run check_image_version.py to flash the correct release'
          ' image! To conduct the check with shell script or gooftool, please'
          ' read the pytest "Description" section.')
