#!/usr/bin/python
#
# Copyright 2016 The Chromium OS Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.


"""Unittests for goofy-specific function for testlog."""

import logging
import os
import re
import shutil
import tempfile
import unittest

import factory_common  # pylint: disable=W0611
from cros.factory.test import testlog_goofy

MAC_RE = re.compile(r'^([a-f0-9]{2}:){5}[a-f0-9]{2}$')
UUID_RE = re.compile(r'^[a-f0-9]{8}-[a-f0-9]{4}-[a-f0-9]{4}-'
                     '[a-f0-9]{4}-[a-f0-9]{12}$')


class TestlogGoofyTest(unittest.TestCase):
  """Unittest for testlog_goofy.py."""

  def setUp(self):
    for _ in [testlog_goofy.REIMAGE_ID_PATH,
              testlog_goofy.DEVICE_ID_PATH,
              testlog_goofy.INIT_COUNT_PATH]:
      try:
        os.unlink(_)
      except OSError:
        pass
    testlog_goofy._reimage_id = None  # pylint: disable=W0212
    testlog_goofy._device_id = None  # pylint: disable=W0212

    self.tmp = tempfile.mkdtemp()

  def tearDown(self):
    shutil.rmtree(self.tmp)

  def testGetBootId(self):
    assert UUID_RE.match(testlog_goofy.GetBootID())

  def testGetDeviceIdGenerateId(self):
    device_id = testlog_goofy.GetDeviceID()
    assert (MAC_RE.match(device_id) or
            UUID_RE.match(device_id)), device_id

    # Remove device_id and make sure we get the same thing
    # back again, re-reading it from disk or the wlan0 interface
    testlog_goofy._device_id = None  # pylint: disable=W0212
    self.assertEqual(device_id, testlog_goofy.GetDeviceID())

    self.assertNotEqual(device_id, testlog_goofy.GetInstallationID())

  def testGetDeviceIdFromSearchPath(self):
    testlog_goofy._device_id = None  # pylint: disable=W0212

    mock_id = 'MOCK_ID'
    device_id_search_path = os.path.join(self.tmp, '.device_id_search')
    with open(device_id_search_path, 'w') as f:
      print >> f, mock_id
    testlog_goofy.DEVICE_ID_SEARCH_PATHS = [device_id_search_path]

    # Device ID should be the same as mock_id every time it is called.
    device_id = testlog_goofy.GetDeviceID()
    self.assertEqual(mock_id, device_id)
    self.assertEqual(mock_id, testlog_goofy.GetDeviceID())

    # Ensure the mock ID remains the same even if search path is gone.
    # i.e. obtains ID from the file
    testlog_goofy._device_id = None  # pylint: disable=W0212
    testlog_goofy.DEVICE_ID_SEARCH_PATHS = []
    self.assertEqual(mock_id, testlog_goofy.GetDeviceID())

  def testGetInstallationID(self):
    reimage_id = testlog_goofy.GetInstallationID()
    assert UUID_RE.match(reimage_id), reimage_id

    # Remove reimage_id and make sure we get the same thing
    # back again, re-reading it from disk
    testlog_goofy._reimage_id = None  # pylint: disable=W0212
    self.assertEqual(reimage_id, testlog_goofy.GetInstallationID())

    # Remove the reimage_id file; now we should get something
    # *different* back.
    testlog_goofy._reimage_id = None  # pylint: disable=W0212
    os.unlink(testlog_goofy.REIMAGE_ID_PATH)
    self.assertNotEqual(reimage_id, testlog_goofy.GetInstallationID())

  def testInitCount(self):
    for i in xrange(-1, 5):
      self.assertEqual(i, testlog_goofy.GetInitCount())
      testlog_goofy.IncrementInitCount()
      self.assertEqual(str(i + 1),
                       open(testlog_goofy.INIT_COUNT_PATH).read())


if __name__ == '__main__':
  logging.basicConfig(
      format=('[%(levelname)s] '
              ' %(threadName)s:%(lineno)d %(asctime)s.%(msecs)03d %(message)s'),
      level=logging.INFO,
      datefmt='%Y-%m-%d %H:%M:%S')
  unittest.main()
