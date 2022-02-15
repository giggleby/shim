# Copyright 2022 The Chromium OS Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

import unittest

from google.cloud import datastore  # pylint: disable=no-name-in-module

from cros.factory.probe_info_service.app_engine import probe_info_storage_connector
from cros.factory.probe_info_service.app_engine import unittest_utils


class DataStoreProbeInfoStorageConnector(unittest.TestCase):

  _qual_id = 1
  _component_id = 2

  def setUp(self):
    self._component_probe_info = unittest_utils.LoadComponentProbeInfo(
        '1-valid')
    self._datastore_client = datastore.Client()
    self._entity_key = self._datastore_client.key(
        'component_probe_info', '%s-%s' % (self._component_id, self._qual_id))
    # pylint: disable=protected-access
    self._connector = (
        probe_info_storage_connector._DataStoreProbeInfoStorageConnector())
    # pylint: enable=protected-access
    self._connector.Clean()

  def testSaveComponentProbeInfo(self):
    self._connector.SaveComponentProbeInfo(self._component_id, self._qual_id,
                                           self._component_probe_info)

    data = self._datastore_client.get(self._entity_key)
    self.assertIn('bytes', data)
    self.assertEqual(self._component_probe_info.SerializeToString(),
                     data['bytes'])

  def testGetComponentProbeInfo(self):
    entity = datastore.Entity(self._entity_key)
    entity.update({'bytes': self._component_probe_info.SerializeToString()})
    self._datastore_client.put(entity)

    returned_component_probe_info = self._connector.GetComponentProbeInfo(
        self._component_id, self._qual_id)

    self.assertEqual(self._component_probe_info, returned_component_probe_info)


if __name__ == '__main__':
  unittest.main()
