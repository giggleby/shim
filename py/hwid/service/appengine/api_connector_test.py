#!/usr/bin/env python3
# Copyright 2022 The Chromium OS Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

import unittest
from unittest import mock

from cros.factory.hwid.service.appengine import api_connector


class HWIDAPIConnectorTest(unittest.TestCase):

  class _FakeResponse:

    def __init__(self, status_code, content):
      self.status_code = status_code
      self.content = content

    def json(self):
      return self.content

  def setUp(self):
    self.connector = api_connector.HWIDAPIConnector()
    self.mock_get_auth_session = mock.patch(
        '__main__.api_connector._GetAuthSession').start()

  def _MockResponse(self, **kwargs):
    mock_session = mock.patch(
        'google.auth.transport.requests.AuthorizedSession').start()
    self.mock_get_auth_session.return_value = mock_session
    mock_session.post.configure_mock(**kwargs)

  def testGetAVLNameMapping(self):
    mapping = {
        1: 'name1',
        2: 'name2',
        3: 'name3'
    }
    self._MockResponse(
        return_value=self._FakeResponse(
            200, {
                'avlNameMappings': [{
                    'componentId': cid,
                    'avlName': avl_name
                } for cid, avl_name in mapping.items()]
            }))
    self.assertEqual(
        self.connector.GetAVLNameMapping([1, 2, 3], batch_size=2), mapping)

  def testGetAVLNameMapping_ServerUnavailable(self):
    self._MockResponse(return_value=self._FakeResponse(404, ''))
    with self.assertRaises(api_connector.HWIDAPIRequestError):
      self.connector.GetAVLNameMapping([1, 2, 3])


if __name__ == '__main__':
  unittest.main()
