#!/usr/bin/env python3
# Copyright 2023 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.
import unittest

from cros.factory.test_list_editor.backend.main import CreateApp


class TestStatusEndpoint(unittest.TestCase):

  def setUp(self) -> None:
    self.app = CreateApp()
    self.client = self.app.test_client()

  def testStatusEndpoint(self):
    response = self.client.get('/status')

    self.assertEqual(response.status_code, 200)
    self.assertEqual(response.get_json(), {'status': 'ok'})


if __name__ == '__main__':
  unittest.main()
