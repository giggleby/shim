#!/usr/bin/env python3
# Copyright 2022 The ChromiumOS Authors.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

import os
import unittest

from cros.factory.utils import file_utils
from cros.factory.utils import gsc_utils


class GSCUtilsTest(unittest.TestCase):
  _GSC_CONSTANTS = """
    #!/bin/sh
    gsc_name() {
      printf "ti50"
    }

    gsc_image_base_name() {
      printf "/opt/google/ti50/firmware/ti50.bin"
    }

    gsc_metrics_prefix() {
      printf "Platform.Ti50"
    }
  """

  def setUp(self):
    self.mock_gsc_constants_path = file_utils.CreateTemporaryFile()

  def tearDown(self):
    if os.path.exists(self.mock_gsc_constants_path):
      os.remove(self.mock_gsc_constants_path)

  def testLoadConstantsFail(self):
    # Function not exists.
    file_utils.WriteFile(self.mock_gsc_constants_path, '#!/bin/sh')
    gsc = gsc_utils.GSCUtils(self.mock_gsc_constants_path)
    with self.assertRaisesRegex(gsc_utils.GSCUtilsError,
                                'Fail to load constant'):
      # gsc.name is a lazy property which triggers the execution of a command
      # on the first call.
      # pylint: disable=pointless-statement
      gsc.name

  def testLoadConstantsSuccess(self):
    file_utils.WriteFile(self.mock_gsc_constants_path, self._GSC_CONSTANTS)
    gsc = gsc_utils.GSCUtils(self.mock_gsc_constants_path)
    self.assertEqual(gsc.name, 'ti50')
    self.assertEqual(gsc.image_base_name, '/opt/google/ti50/firmware/ti50.bin')
    self.assertEqual(gsc.metrics_prefix, 'Platform.Ti50')
    self.assertTrue(gsc.IsTi50())
    self.assertListEqual(gsc.GetGSCToolCmd(), [gsc_utils.GSCTOOL_PATH, '-D'])


if __name__ == '__main__':
  unittest.main()
