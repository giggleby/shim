# Copyright 2023 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

import unittest
from unittest import mock

from cros.factory.bundle_creator.app_engine_v2 import stubby_handler
from cros.factory.bundle_creator.proto import factorybundle_v2_pb2  # pylint: disable=no-name-in-module


class StubbyHandlerTest(unittest.TestCase):

  def setUp(self):
    mock_flask_patcher = mock.patch(
        'cros.factory.bundle_creator.utils.allowlist_utils.flask')
    mock_flask = mock_flask_patcher.start()
    mock_flask.request.headers = {
        'X-Appengine-Loas-Peer-Username': 'foobar',
    }
    self.addCleanup(mock_flask_patcher.stop)

    self._stubby_handler = stubby_handler.FactoryBundleServiceV2()

  def testEcho_succeed_verifiesResponse(self):
    message = 'This is a fake message.'
    request = factorybundle_v2_pb2.EchoRequest()
    request.message = message

    response = self._stubby_handler.Echo(request)

    expected_response = factorybundle_v2_pb2.EchoResponse()
    expected_response.message = message
    self.assertEqual(response, expected_response)


if __name__ == '__main__':
  unittest.main()
