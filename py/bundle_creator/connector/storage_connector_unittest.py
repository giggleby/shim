# Copyright 2022 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

import datetime
import unittest
from unittest import mock

from cros.factory.bundle_creator.connector import storage_connector
from cros.factory.bundle_creator.proto import factorybundle_v2_pb2  # pylint: disable=no-name-in-module


StorageBundleMetadata = storage_connector.StorageBundleMetadata
StorageBundleInfo = storage_connector.StorageBundleInfo


class StorageBundleMetadataTest(unittest.TestCase):

  def setUp(self):
    self._metadata = StorageBundleMetadata(
        doc_id='unused_doc_id', email='foo@bar', board='board',
        project='project', phase='proto', toolkit_version='11111.0.0',
        test_image_version='22222.0.0', release_image_version='33333.0.0')

  def testToV2BundleMetadata_succeed_returnsExpectedValue(self):
    metadata = self._metadata.ToV2BundleMetadata()

    expected_metadata = factorybundle_v2_pb2.BundleMetadata()
    expected_metadata.board = 'board'
    expected_metadata.project = 'project'
    expected_metadata.phase = 'proto'
    expected_metadata.toolkit_version = '11111.0.0'
    expected_metadata.test_image_version = '22222.0.0'
    expected_metadata.release_image_version = '33333.0.0'
    self.assertEqual(metadata, expected_metadata)

  def testToV2BundleMetadata_hasFirmwareSource_verifiesFirmwareSource(self):
    firmware_source = '44444.0.0'
    self._metadata.firmware_source = firmware_source

    metadata = self._metadata.ToV2BundleMetadata()

    self.assertEqual(metadata.firmware_source, firmware_source)


class StorageBundleInfoTest(unittest.TestCase):

  def testFilename_succeed_returnsExpectedValue(self):
    filename = 'fake_filename'
    metadata = StorageBundleMetadata(
        doc_id='unused_doc_id', email='foo@bar', board='board',
        project='project', phase='proto', toolkit_version='11111.0.0',
        test_image_version='22222.0.0', release_image_version='33333.0.0')
    info = StorageBundleInfo(blob_path=f'board/project/{filename}',
                             metadata=metadata,
                             created_timestamp_sec=1672161699)

    self.assertEqual(info.filename, filename)


class StorageConnectorTest(unittest.TestCase):

  _CLOUD_PROJECT_ID = 'fake-project-id'
  _BUCKET_NAME = 'fake-bucket'

  def setUp(self):
    self._mock_blob = mock.Mock()
    self._mock_bucket = mock.Mock()
    self._mock_bucket.blob.return_value = self._mock_blob
    mock_storage_patcher = mock.patch('google.cloud.storage.Client')
    mock_client = mock_storage_patcher.start().return_value
    mock_client.get_bucket.return_value = self._mock_bucket
    self.addCleanup(mock_storage_patcher.stop)

    self._connector = storage_connector.StorageConnector(
        self._CLOUD_PROJECT_ID, self._BUCKET_NAME)

  def testGrantReadPermissionToBlob_succeed_verifyCallingBucketAndAcl(self):
    email = 'foo@bar'
    blob_path = 'board/project/fake.tar.bz2'
    mock_blob = mock.Mock()
    self._mock_bucket.get_blob.return_value = mock_blob
    mock_user_entity = mock.Mock()
    mock_blob.acl.user.return_value = mock_user_entity

    self._connector.GrantReadPermissionToBlob(email, blob_path)

    self._mock_bucket.get_blob.assert_called_once_with(blob_path)
    mock_blob.acl.user.assert_called_once_with(email)
    mock_user_entity.grant_read.assert_called_once()
    mock_blob.acl.save.assert_called_once()

  def testReadFile_succeed(self):
    self._mock_bucket.blob.return_value.download_as_string.return_value = (
        'fake_content')

    self.assertEqual('fake_content', self._connector.ReadFile('fake_path'))


class FactoryBundleStorageConnectorTest(unittest.TestCase):

  _CLOUD_PROJECT_ID = 'fake-project-id'
  _BUCKET_NAME = 'fake-bucket'
  _BUNDLE_PATH = '/tmp/fake_bundle_path'
  _EXPECTED_FILENAME = (
      'factory_bundle_project_20220508_0000_proto_00000.tar.bz2')

  def setUp(self):
    self._bundle_metadata = storage_connector.StorageBundleMetadata(
        doc_id='FakeDocId', email='foo@bar', board='board', project='project',
        phase='proto', toolkit_version='11111.0.0',
        test_image_version='22222.0.0', release_image_version='33333.0.0')

    mock_datetime_patcher = mock.patch(
        'cros.factory.bundle_creator.connector.storage_connector.datetime')
    mock_datetime = mock_datetime_patcher.start()
    mock_datetime.now.return_value = datetime.datetime(2022, 5, 8, 0, 0)
    mock_datetime.timestamp.side_effect = datetime.datetime.timestamp
    self.addCleanup(mock_datetime_patcher.stop)

    self._mock_blob = mock.Mock()
    self._mock_bucket = mock.Mock()
    self._mock_bucket.blob.return_value = self._mock_blob
    mock_storage_patcher = mock.patch('google.cloud.storage.Client')
    mock_client = mock_storage_patcher.start().return_value
    mock_client.get_bucket.return_value = self._mock_bucket
    self.addCleanup(mock_storage_patcher.stop)

    self._connector = storage_connector.FactoryBundleStorageConnector(
        self._CLOUD_PROJECT_ID, self._BUCKET_NAME)

  def testUploadCreatedBundle_verifyInitializesBlobWithExpectedValues(self):
    self._connector.UploadCreatedBundle(self._BUNDLE_PATH,
                                        self._bundle_metadata)

    self.assertEqual(self._mock_bucket.blob.call_args.args[0],
                     f'board/project/{self._EXPECTED_FILENAME}')
    self.assertEqual(self._mock_blob.content_disposition,
                     f'filename="{self._EXPECTED_FILENAME}"')
    self._mock_blob.upload_from_filename.assert_called_once_with(
        self._BUNDLE_PATH)

  def testUploadCreatedBundle_withoutFirmwareSource_verifyUpdateMetadata(self):
    created_timestamp = 1651939200
    self._mock_blob.time_created.timestamp.return_value = created_timestamp

    self._connector.UploadCreatedBundle(self._BUNDLE_PATH,
                                        self._bundle_metadata)

    self.assertEqual(
        self._mock_blob.metadata, {
            'Bundle-Creator': 'foo@bar',
            'Phase': 'proto',
            'Tookit-Version': '11111.0.0',
            'Test-Image-Version': '22222.0.0',
            'Release-Image-Version': '33333.0.0',
            'User-Request-Doc-Id': 'FakeDocId',
            'Time-Created': created_timestamp,
        })
    self._mock_blob.update.assert_called_once()

  def testUploadCreatedBundle_withFirmwareSource_verifyUpdateMetadata(self):
    created_timestamp = 1651939200
    self._mock_blob.time_created.timestamp.return_value = created_timestamp
    self._bundle_metadata.firmware_source = '44444.0.0'

    self._connector.UploadCreatedBundle(self._BUNDLE_PATH,
                                        self._bundle_metadata)

    self.assertEqual(
        self._mock_blob.metadata, {
            'Bundle-Creator': 'foo@bar',
            'Phase': 'proto',
            'Tookit-Version': '11111.0.0',
            'Test-Image-Version': '22222.0.0',
            'Release-Image-Version': '33333.0.0',
            'User-Request-Doc-Id': 'FakeDocId',
            'Time-Created': created_timestamp,
            'Firmware-Source': '44444.0.0',
        })
    self._mock_blob.update.assert_called_once()

  def testUploadCreatedBundle_returnsExpectedGsPath(self):
    gs_path = self._connector.UploadCreatedBundle(self._BUNDLE_PATH,
                                                  self._bundle_metadata)

    self.assertEqual(
        gs_path, f'gs://fake-bucket/board/project/{self._EXPECTED_FILENAME}')

  def testGetBundleInfosByProject_singleBlob_returnsExpectedValue(self):
    project = 'project'
    created_timestamp_sec = 1672750600
    self._mock_bucket.list_blobs.return_value = [
        self._CreateMockBlob(project, created_timestamp_sec),
    ]

    infos = self._connector.GetBundleInfosByProject(project)

    self.assertEqual(infos, [
        StorageBundleInfo(
            blob_path=f'fake_board/{project}/fake_bundle.tar.bz2',
            metadata=StorageBundleMetadata(
                doc_id='FakeDocId', email='foo@bar', board='fake_board',
                project='project', phase='proto', toolkit_version='11111.0.0',
                test_image_version='22222.0.0',
                release_image_version='33333.0.0', firmware_source='44444.0.0'),
            created_timestamp_sec=created_timestamp_sec)
    ])

  def testGetBundleInfosByProject_filterWithProject_verifiesReturnInfos(self):
    project = 'project'
    created_timestamp_sec1 = 1672750600
    created_timestamp_sec2 = 1672750800
    self._mock_bucket.list_blobs.return_value = [
        self._CreateMockBlob(project, created_timestamp_sec1),
        self._CreateMockBlob('other-project', 1672750700),
        self._CreateMockBlob(project, created_timestamp_sec2),
    ]

    infos = self._connector.GetBundleInfosByProject(project)

    self.assertEqual(len(infos), 2)
    self.assertEqual(infos[0].created_timestamp_sec, created_timestamp_sec1)
    self.assertEqual(infos[1].created_timestamp_sec, created_timestamp_sec2)

  def testGetBundleInfosByProject_useTimeCreated_verifiesCreatedTimestamp(self):
    project = 'project'
    mock_blob = mock.Mock(
        metadata={}, time_created=datetime.datetime(
            2023, 1, 3, 12, 56, 40,
            tzinfo=datetime.timezone(datetime.timedelta())))
    mock_blob.name = f'board/{project}/fake_bundle.tar.bz2'
    self._mock_bucket.list_blobs.return_value = [mock_blob]

    infos = self._connector.GetBundleInfosByProject(project)

    self.assertEqual(len(infos), 1)
    self.assertEqual(infos[0].created_timestamp_sec, 1672750600)

  def _CreateMockBlob(self, project: str, created_timestamp_sec: int):
    mock_blob = mock.Mock(
        metadata={
            'User-Request-Doc-Id': 'FakeDocId',
            'Bundle-Creator': 'foo@bar',
            'Phase': 'proto',
            'Tookit-Version': '11111.0.0',
            'Test-Image-Version': '22222.0.0',
            'Release-Image-Version': '33333.0.0',
            'Firmware-Source': '44444.0.0',
            'Time-Created': created_timestamp_sec,
        }, time_created=datetime.datetime.fromtimestamp(created_timestamp_sec))
    # The `name` attribute can't be mocked while creating the mock object.
    mock_blob.name = f'fake_board/{project}/fake_bundle.tar.bz2'
    return mock_blob


if __name__ == '__main__':
  unittest.main()
