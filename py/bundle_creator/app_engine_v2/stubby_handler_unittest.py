# Copyright 2023 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

import unittest
from unittest import mock

from cros.factory.bundle_creator.app_engine_v2 import stubby_handler
from cros.factory.bundle_creator.connector import firestore_connector
from cros.factory.bundle_creator.proto import factorybundle_v2_pb2  # pylint: disable=no-name-in-module


class StubbyHandlerTest(unittest.TestCase):

  def setUp(self):
    self._create_bundle_request = factorybundle_v2_pb2.CreateBundleRequest()
    self._create_bundle_request.email = 'foo@bar'
    bundle_metadata = self._create_bundle_request.bundle_metadata
    bundle_metadata.board = 'board'
    bundle_metadata.project = 'project'
    bundle_metadata.phase = 'proto'
    bundle_metadata.toolkit_version = '11111.0.0'
    bundle_metadata.test_image_version = '22222.0.0'
    bundle_metadata.release_image_version = '33333.0.0'
    self._create_bundle_request.hwid_option.update_db_firmware_info = False

    mock_flask_patcher = mock.patch(
        'cros.factory.bundle_creator.utils.allowlist_utils.flask')
    mock_flask = mock_flask_patcher.start()
    mock_flask.request.headers = {
        'X-Appengine-Loas-Peer-Username': 'foobar',
    }
    self.addCleanup(mock_flask_patcher.stop)

    self._doc_id = 'fake-doc-id'
    self._mock_firestore_connector = mock.Mock()
    self._mock_firestore_connector.CreateUserRequest.return_value = self._doc_id
    mock_firestore_connector_patcher = mock.patch(
        'cros.factory.bundle_creator.connector'
        '.firestore_connector.FirestoreConnector')
    mock_firestore_connector_patcher.start().return_value = (
        self._mock_firestore_connector)
    self.addCleanup(mock_firestore_connector_patcher.stop)

    self._mock_pubsub_connector = mock.Mock()
    mock_pubsub_connector_patcher = mock.patch(
        'cros.factory.bundle_creator.connector'
        '.pubsub_connector.PubSubConnector')
    mock_pubsub_connector_patcher.start().return_value = (
        self._mock_pubsub_connector)
    self.addCleanup(mock_pubsub_connector_patcher.stop)

    self._stubby_handler = stubby_handler.FactoryBundleServiceV2()

  def testCreateBundle_succeed_returnsExpectedResponse(self):
    response = self._stubby_handler.CreateBundle(self._create_bundle_request)

    expected_response = factorybundle_v2_pb2.CreateBundleResponse()
    expected_response.status = expected_response.Status.NO_ERROR
    self.assertEqual(response, expected_response)

  def testCreateBundle_succeed_verifiesCallingConnectors(self):
    self._stubby_handler.CreateBundle(self._create_bundle_request)

    expected_message = factorybundle_v2_pb2.CreateBundleMessage()
    expected_message.doc_id = self._doc_id
    expected_message.request.MergeFrom(self._create_bundle_request)
    self._mock_firestore_connector.CreateUserRequest.assert_called_once_with(
        firestore_connector.CreateBundleRequestInfo.FromV2CreateBundleRequest(
            self._create_bundle_request), 'v2')
    self._mock_pubsub_connector.PublishMessage.assert_called_once_with(
        'fake-topic', expected_message.SerializeToString(),
        {'request_from': 'v2'})


if __name__ == '__main__':
  unittest.main()
