#!/usr/bin/env python3
# Copyright 2023 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

import unittest

from cros.factory.test.pytests import branded_chassis


class BrandedChassisUnittest(unittest.TestCase):

  def testNoExistingData(self):
    existing_data = None
    response = False
    self.assertFalse(
        branded_chassis.IsInconsistentResponse(existing_data, response))

  def testExistingMatchFalse(self):
    existing_data = False
    response = False
    self.assertFalse(
        branded_chassis.IsInconsistentResponse(existing_data, response))

  def testExistingMatchTrue(self):
    existing_data = True
    response = True
    self.assertFalse(
        branded_chassis.IsInconsistentResponse(existing_data, response))

  def testExistingMatchInconsistent(self):
    existing_data = True
    response = False
    self.assertTrue(
        branded_chassis.IsInconsistentResponse(existing_data, response))
