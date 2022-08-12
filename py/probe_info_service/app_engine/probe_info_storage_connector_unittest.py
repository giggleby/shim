# Copyright 2022 The Chromium OS Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

import unittest

from cros.factory.probe_info_service.app_engine import probe_info_storage_connector
from cros.factory.probe_info_service.app_engine import unittest_utils


class DataStoreProbeInfoStorageConnector(unittest.TestCase):

  def setUp(self):
    super().setUp()

    # pylint: disable=protected-access
    self._connector = (
        probe_info_storage_connector._DataStoreProbeInfoStorageConnector())
    # pylint: enable=protected-access

  def tearDown(self):
    super().tearDown()
    self._connector.Clean()

  def testSaveAndLoad(self):
    """Save some data and load it back to verify the functionalities."""
    comp_id = 2
    qual_id = 1
    comp_probe_info = unittest_utils.LoadComponentProbeInfo('1-valid')

    self._connector.SaveComponentProbeInfo(comp_id, qual_id, comp_probe_info)
    loaded_comp_probe_info = self._connector.GetComponentProbeInfo(
        comp_id, qual_id)

    self.assertEqual(comp_probe_info, loaded_comp_probe_info)

  def testGetComponentProbeInfo_WhenNotFoundThenReturnNone(self):
    comp_probe_info = self._connector.GetComponentProbeInfo(123, 456)

    self.assertIsNone(comp_probe_info)


if __name__ == '__main__':
  unittest.main()
