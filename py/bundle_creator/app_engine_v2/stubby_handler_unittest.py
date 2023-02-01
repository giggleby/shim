# Copyright 2023 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

import datetime
from typing import Dict
import unittest
from unittest import mock

from google.api_core.datetime_helpers import DatetimeWithNanoseconds
import pytz

# isort: split

from cros.factory.bundle_creator.app_engine_v2 import stubby_handler
from cros.factory.bundle_creator.connector import firestore_connector
from cros.factory.bundle_creator.connector import storage_connector
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

    self._get_bundle_info_request = factorybundle_v2_pb2.GetBundleInfoRequest()
    self._get_bundle_info_request.email = 'foo@bar'
    self._get_bundle_info_request.project = 'project'

    self._download_bundle_request = factorybundle_v2_pb2.DownloadBundleRequest()
    self._download_bundle_request.email = 'foo@bar'
    self._download_bundle_request.blob_path = 'board/project/fake.tar.bz2'

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

    self._mock_storage_connector = mock.Mock()
    mock_storage_connector_patcher = mock.patch(
        'cros.factory.bundle_creator.connector'
        '.storage_connector.StorageConnector')
    mock_storage_connector_patcher.start().return_value = (
        self._mock_storage_connector)
    self.addCleanup(mock_storage_connector_patcher.stop)

    self._stubby_handler = stubby_handler.FactoryBundleV2Service()

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

  def testGetBundleInfo_succeed_returnsExpectedResponse(self):
    base_timestamp_sec = 1672750600
    base_datetime = DatetimeWithNanoseconds(2023, 1, 3, 12, 56, 40,
                                            tzinfo=pytz.UTC)
    error_message = 'Fake error message.'
    self._mock_storage_connector.GetBundleInfosByProject.return_value = [
        self._CreateStorageBundleInfo('foo@bar', 'fake_bundle_1.tar.bz2',
                                      base_timestamp_sec),
        self._CreateStorageBundleInfo('foo2@bar', 'fake_bundle_2.tar.bz2',
                                      base_timestamp_sec + 100),
    ]
    self._mock_firestore_connector.GetUserRequestsByEmail.return_value = [
        self._CreateUserRequest(
            firestore_connector.UserRequestStatus.SUCCEEDED, base_datetime,
            start_time=base_datetime + datetime.timedelta(seconds=1),
            end_time=base_datetime + datetime.timedelta(seconds=2)),
        self._CreateUserRequest(
            firestore_connector.UserRequestStatus.NOT_STARTED,
            base_datetime + datetime.timedelta(seconds=200)),
        self._CreateUserRequest(
            firestore_connector.UserRequestStatus.IN_PROGRESS,
            base_datetime + datetime.timedelta(seconds=300),
            start_time=base_datetime + datetime.timedelta(seconds=301)),
        self._CreateUserRequest(
            firestore_connector.UserRequestStatus.FAILED,
            base_datetime + datetime.timedelta(seconds=400),
            start_time=base_datetime + datetime.timedelta(seconds=401),
            end_time=base_datetime + datetime.timedelta(seconds=402),
            error_message=error_message),
    ]

    response = self._stubby_handler.GetBundleInfo(self._get_bundle_info_request)

    expected_response = factorybundle_v2_pb2.GetBundleInfoResponse()
    expected_response.bundle_infos.append(
        self._CreateBundleInfo('foo@bar',
                               firestore_connector.UserRequestStatus.FAILED,
                               request_time_sec=base_timestamp_sec + 400,
                               request_start_time_sec=base_timestamp_sec + 401,
                               request_end_time_sec=base_timestamp_sec + 402,
                               error_message=error_message))
    expected_response.bundle_infos.append(
        self._CreateBundleInfo(
            'foo@bar', firestore_connector.UserRequestStatus.IN_PROGRESS,
            request_time_sec=base_timestamp_sec + 300,
            request_start_time_sec=base_timestamp_sec + 301))
    expected_response.bundle_infos.append(
        self._CreateBundleInfo(
            'foo@bar', firestore_connector.UserRequestStatus.NOT_STARTED,
            request_time_sec=base_timestamp_sec + 200))
    expected_response.bundle_infos.append(
        self._CreateBundleInfo(
            'foo2@bar', firestore_connector.UserRequestStatus.SUCCEEDED,
            blob_path='board/project/fake_bundle_2.tar.bz2',
            filename='fake_bundle_2.tar.bz2',
            bundle_created_timestamp_sec=base_timestamp_sec + 100))
    expected_response.bundle_infos.append(
        self._CreateBundleInfo('foo@bar',
                               firestore_connector.UserRequestStatus.SUCCEEDED,
                               blob_path='board/project/fake_bundle_1.tar.bz2',
                               filename='fake_bundle_1.tar.bz2',
                               bundle_created_timestamp_sec=base_timestamp_sec))
    self.assertEqual(response, expected_response)

  def testDownloadBundle_succeed_returnsExpectedResponse(self):
    response = self._stubby_handler.DownloadBundle(
        self._download_bundle_request)

    expected_response = factorybundle_v2_pb2.DownloadBundleResponse()
    expected_response.download_link = (
        f'https://storage.cloud.google.com/fake-bundle-bucket/'
        f'{self._download_bundle_request.blob_path}')
    self.assertEqual(response, expected_response)

  def testDownloadBundle_succeed_verifiesCallingConnector(self):
    self._stubby_handler.DownloadBundle(self._download_bundle_request)

    method = self._mock_storage_connector.GrantReadPermissionToBlob
    method.assert_called_once_with(self._download_bundle_request.email,
                                   self._download_bundle_request.blob_path)

  def _CreateStorageBundleInfo(
      self, email: str, filename: str,
      created_timestamp_sec: int) -> storage_connector.StorageBundleInfo:
    return storage_connector.StorageBundleInfo(
        blob_path=f'board/project/{filename}',
        metadata=storage_connector.StorageBundleMetadata(
            doc_id='FakeDocId', email=email, board='board', project='project',
            phase='proto', toolkit_version='11111.0.0',
            test_image_version='22222.0.0', release_image_version='33333.0.0',
            firmware_source='44444.0.0'),
        created_timestamp_sec=created_timestamp_sec)

  def _CreateUserRequest(self, status: firestore_connector.UserRequestStatus,
                         request_time: DatetimeWithNanoseconds,
                         **kwargs) -> Dict[str, any]:
    snapshot = {
        'board': 'board',
        'project': 'project',
        'phase': 'proto',
        'toolkit_version': '11111.0.0',
        'test_image_version': '22222.0.0',
        'release_image_version': '33333.0.0',
        'firmware_source': '44444.0.0',
        'email': 'foo@bar',
        'status': status.name,
        'request_time': request_time,
    }
    if 'start_time' in kwargs:
      snapshot['start_time'] = kwargs['start_time']
    if 'end_time' in kwargs:
      snapshot['end_time'] = kwargs['end_time']
    if 'error_message' in kwargs:
      snapshot['error_message'] = kwargs['error_message']
    return snapshot

  def _CreateBundleInfo(self, creator: str,
                        status: firestore_connector.UserRequestStatus,
                        **kwargs) -> factorybundle_v2_pb2.BundleInfo:
    info = factorybundle_v2_pb2.BundleInfo()
    info.metadata.board = 'board'
    info.metadata.project = 'project'
    info.metadata.phase = 'proto'
    info.metadata.toolkit_version = '11111.0.0'
    info.metadata.test_image_version = '22222.0.0'
    info.metadata.release_image_version = '33333.0.0'
    info.metadata.firmware_source = '44444.0.0'
    info.creator = creator
    info.status = status.name
    if 'blob_path' in kwargs:
      info.blob_path = kwargs['blob_path']
    if 'filename' in kwargs:
      info.filename = kwargs['filename']
    if 'request_time_sec' in kwargs:
      info.request_time_sec = kwargs['request_time_sec']
    if 'request_start_time_sec' in kwargs:
      info.request_start_time_sec = kwargs['request_start_time_sec']
    if 'request_end_time_sec' in kwargs:
      info.request_end_time_sec = kwargs['request_end_time_sec']
    if 'bundle_created_timestamp_sec' in kwargs:
      info.bundle_created_timestamp_sec = kwargs['bundle_created_timestamp_sec']
    if 'error_message' in kwargs:
      info.error_message = kwargs['error_message']
    return info


if __name__ == '__main__':
  unittest.main()
