# Copyright 2022 The ChromiumOS Authors.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

import datetime
import os
import shutil
import tempfile
from time import sleep
from typing import Dict, List
import unittest
from unittest import mock

from google.api_core.datetime_helpers import DatetimeWithNanoseconds
from google.cloud import firestore  # pylint: disable=no-name-in-module,import-error
import pytz
import yaml

from cros.factory.bundle_creator.connector import firestore_connector
from cros.factory.bundle_creator.connector import hwid_api_connector
from cros.factory.bundle_creator.connector import pubsub_connector
from cros.factory.bundle_creator.docker import config
from cros.factory.bundle_creator.docker import worker
from cros.factory.bundle_creator.proto import factorybundle_pb2  # pylint: disable=no-name-in-module
from cros.factory.utils import file_utils
from cros.factory.utils import process_utils

_BUNDLE_RECORD = '{"fake_key": "fake_value"}'


def _MockFinalizeBundle(command: List[str], **kwargs) -> str:
  if 'stderr' not in kwargs or kwargs['stderr'] != process_utils.STDOUT:
    raise ValueError('STDERR should be redirected to STDOUT.')

  if command[0] != '/usr/local/factory/factory.par' or command[
      1] != 'finalize_bundle':
    raise ValueError('Wrong arguments for calling `finalize_bundle`.')

  manifest_path = command[2]
  if not os.path.exists(manifest_path):
    raise ValueError(f'The manifest file `{manifest_path}` doesn\'t exist.')

  if '--bundle-record' in command:
    bundle_record_path = command[command.index('--bundle-record') + 1]
    file_utils.WriteFile(bundle_record_path, _BUNDLE_RECORD)

  manifest = yaml.safe_load(file_utils.ReadFile(manifest_path))
  factory_bundle_path = os.path.join(
      os.path.dirname(manifest_path),
      f'factory_bundle_{manifest["project"]}_{manifest["bundle_name"]}.tar.bz2')
  file_utils.WriteFile(factory_bundle_path, 'fake_bundle')
  return 'fake_output'


class EasyBundleCreationWorkerTest(unittest.TestCase):

  _TOPIC_NAME = 'fake-topic'
  _GS_PATH = 'gs://fake_path'
  _FIRESTORE_CURRENT_DATETIME = DatetimeWithNanoseconds(2022, 6, 8, 0, 0,
                                                        tzinfo=pytz.UTC)

  @classmethod
  def setUpClass(cls):
    cls._firestore_connector = firestore_connector.FirestoreConnector(
        config.GCLOUD_PROJECT)
    cls._pubsub_connector = pubsub_connector.PubSubConnector(
        config.GCLOUD_PROJECT)
    cls._pubsub_connector.CreateTopic(cls._TOPIC_NAME)

  @classmethod
  def tearDownClass(cls):
    cls._pubsub_connector.DeleteTopic(cls._TOPIC_NAME)

  def setUp(self):
    self._MockDatetime(
        'cros.factory.bundle_creator.connector.firestore_connector')
    self._MockDatetime('cros.factory.bundle_creator.docker.worker')

    mock_check_output_patcher = mock.patch(
        'cros.factory.utils.process_utils.LogAndCheckOutput')
    self._mock_check_output = mock_check_output_patcher.start()
    self._mock_check_output.side_effect = _MockFinalizeBundle
    self.addCleanup(mock_check_output_patcher.stop)

    self._temp_dir_path = tempfile.mkdtemp()
    mock_temp_dir_patcher = mock.patch(
        'cros.factory.utils.file_utils.TempDirectory')
    mock_temp_dir = mock_temp_dir_patcher.start()
    mock_temp_dir.return_value.__enter__.return_value = self._temp_dir_path
    self.addCleanup(mock_temp_dir_patcher.stop)

    self._message = factorybundle_pb2.CreateBundleMessage()
    self._message.request.board = 'board'
    self._message.request.project = 'project'
    self._message.request.phase = 'proto'
    self._message.request.toolkit_version = '11111.0.0'
    self._message.request.test_image_version = '22222.0.0'
    self._message.request.release_image_version = '33333.0.0'
    self._message.request.email = 'foo@bar'
    self._firestore_connector.ClearCollection('user_requests')
    self._firestore_connector.ClearCollection('has_firmware_settings')
    self._message.doc_id = (
        self._firestore_connector.CreateUserRequest(self._message.request))
    self._pubsub_connector.CreateSubscription(self._TOPIC_NAME,
                                              config.PUBSUB_SUBSCRIPTION)

    self._mock_cloudtasks_connector = mock.Mock()
    self._mock_hwid_api_connector = mock.Mock()
    self._mock_storage_connector = mock.Mock()
    self._MockConnector('cloudtasks_connector.CloudTasksConnector',
                        self._mock_cloudtasks_connector)
    self._MockConnector('hwid_api_connector.HWIDAPIConnector',
                        self._mock_hwid_api_connector)
    self._MockConnector('storage_connector.StorageConnector',
                        self._mock_storage_connector)
    self._mock_storage_connector.UploadCreatedBundle.return_value = (
        self._GS_PATH)
    self._worker = worker.EasyBundleCreationWorker()

  def tearDown(self):
    self._pubsub_connector.DeleteSubscription(config.PUBSUB_SUBSCRIPTION)
    if os.path.exists(self._temp_dir_path):
      shutil.rmtree(self._temp_dir_path)

  def testTryProcessRequest_bundleCreationSucceed_verifiesResultHandling(self):
    self._PublishCreateBundleMessage()

    self._worker.TryProcessRequest()

    doc = self._firestore_connector.GetUserRequestDocument(self._message.doc_id)
    expected_worker_result = factorybundle_pb2.WorkerResult()
    expected_worker_result.status = factorybundle_pb2.WorkerResult.NO_ERROR
    expected_worker_result.original_request.MergeFrom(self._message.request)
    expected_worker_result.gs_path = self._GS_PATH
    mock_method = self._mock_cloudtasks_connector.ResponseWorkerResult
    self.assertEqual(doc['status'],
                     self._firestore_connector.USER_REQUEST_STATUS_SUCCEEDED)
    self.assertEqual(doc['start_time'], self._FIRESTORE_CURRENT_DATETIME)
    self.assertEqual(doc['end_time'], self._FIRESTORE_CURRENT_DATETIME)
    self.assertEqual(doc['gs_path'], self._GS_PATH)
    mock_method.assert_called_once_with(expected_worker_result)

  def testTryProcessRequest_bundleCreationFailed_verifiesResultHandling(self):
    error_message = 'fake_error_message'
    self._mock_check_output.side_effect = process_utils.CalledProcessError(
        -1, None, error_message)
    self._PublishCreateBundleMessage()

    self._worker.TryProcessRequest()

    doc = self._firestore_connector.GetUserRequestDocument(self._message.doc_id)
    expected_worker_result = factorybundle_pb2.WorkerResult()
    expected_worker_result.status = factorybundle_pb2.WorkerResult.FAILED
    expected_worker_result.original_request.MergeFrom(self._message.request)
    expected_worker_result.error_message = error_message
    mock_method = self._mock_cloudtasks_connector.ResponseWorkerResult
    self.assertEqual(doc['status'],
                     self._firestore_connector.USER_REQUEST_STATUS_FAILED)
    self.assertEqual(doc['end_time'], self._FIRESTORE_CURRENT_DATETIME)
    self.assertEqual(doc['error_message'], error_message)
    mock_method.assert_called_once_with(expected_worker_result)

  def testTryProcessRequest_createHWIDCLSucceed_verifiesResultHandling(self):
    cl_url = ['https://fake_cl_url']
    self._mock_hwid_api_connector.CreateHWIDFirmwareInfoCL.return_value = cl_url
    self._message.request.update_hwid_db_firmware_info = True
    self._message.request.hwid_related_bug_number = 123456789
    self._PublishCreateBundleMessage()

    self._worker.TryProcessRequest()

    doc = self._firestore_connector.GetUserRequestDocument(self._message.doc_id)
    expected_worker_result = factorybundle_pb2.WorkerResult()
    expected_worker_result.status = factorybundle_pb2.WorkerResult.NO_ERROR
    expected_worker_result.original_request.MergeFrom(self._message.request)
    expected_worker_result.gs_path = self._GS_PATH
    expected_worker_result.cl_url.extend(cl_url)
    mock_method = self._mock_cloudtasks_connector.ResponseWorkerResult
    self.assertEqual(doc['hwid_cl_url'], cl_url)
    mock_method.assert_called_once_with(expected_worker_result)

  def testTryProcessRequest_createHWIDCLFailed_verifiesResultHandling(self):
    error_message = '{"fake_error": "fake_message"}'
    self._mock_hwid_api_connector.CreateHWIDFirmwareInfoCL.side_effect = (
        hwid_api_connector.HWIDAPIRequestException(error_message))
    self._message.request.update_hwid_db_firmware_info = True
    self._message.request.hwid_related_bug_number = 123456789
    self._PublishCreateBundleMessage()

    self._worker.TryProcessRequest()

    doc = self._firestore_connector.GetUserRequestDocument(self._message.doc_id)
    expected_worker_result = factorybundle_pb2.WorkerResult()
    expected_worker_result.status = (
        factorybundle_pb2.WorkerResult.CREATE_CL_FAILED)
    expected_worker_result.original_request.MergeFrom(self._message.request)
    expected_worker_result.gs_path = self._GS_PATH
    expected_worker_result.error_message = error_message
    mock_method = self._mock_cloudtasks_connector.ResponseWorkerResult
    self.assertEqual(doc['hwid_cl_error_msg'], error_message)
    mock_method.assert_called_once_with(expected_worker_result)

  def testTryProcessRequest_withoutFirmwareSource_verifiesManifest(self):
    self._PublishCreateBundleMessage()

    self._worker.TryProcessRequest()

    expected_manifest = {
        'board': self._message.request.board,
        'project': self._message.request.project,
        'designs': 'boxster_designs',
        'bundle_name': f'20220608_{self._message.request.phase}',
        'toolkit': self._message.request.toolkit_version,
        'test_image': self._message.request.test_image_version,
        'release_image': self._message.request.release_image_version,
        'firmware': 'release_image',
    }
    self.assertEqual(self._ReadManifest(), expected_manifest)

  def testTryProcessRequest_hasFirmwareSource_verifiesManifest(self):
    self._message.request.firmware_source = '44444.0.0'
    self._PublishCreateBundleMessage()

    self._worker.TryProcessRequest()

    manifest = self._ReadManifest()
    self.assertEqual(manifest['firmware'], 'release_image/44444.0.0')

  def testTryProcessRequest_hasFirmwareSetting_verifiesManifest(self):
    has_firmware_setting_value = ['BIOS']
    firestore_client = firestore.Client(project=config.GCLOUD_PROJECT)
    firestore_client.collection('has_firmware_settings').document(
        self._message.request.project).set(
            {'has_firmware': has_firmware_setting_value})
    self._PublishCreateBundleMessage()

    self._worker.TryProcessRequest()

    manifest = self._ReadManifest()
    self.assertEqual(manifest['has_firmware'], has_firmware_setting_value)

  def testTryProcessRequest_succeed_verifiesCallingStorageConnector(self):
    self._PublishCreateBundleMessage()

    self._worker.TryProcessRequest()

    args = self._mock_storage_connector.UploadCreatedBundle.call_args.args
    self.assertTrue(os.path.exists(args[0]))
    self.assertEqual(args[1], self._message)

  def testTryProcessRequest_succeed_verifiesCallingHWIDAPIConnector(self):
    self._mock_hwid_api_connector.CreateHWIDFirmwareInfoCL.return_value = [
        'https://fake_cl_url'
    ]
    self._message.request.update_hwid_db_firmware_info = True
    self._message.request.hwid_related_bug_number = 123456789
    self._PublishCreateBundleMessage()

    self._worker.TryProcessRequest()

    mock_method = self._mock_hwid_api_connector.CreateHWIDFirmwareInfoCL
    mock_method.assert_called_once_with(
        _BUNDLE_RECORD, self._message.request.email,
        self._message.request.hwid_related_bug_number,
        self._message.request.phase)

  def _MockDatetime(self, module_name: str):
    mock_datetime_patcher = mock.patch(f'{module_name}.datetime')
    mock_datetime_patcher.start().now.return_value = datetime.datetime(
        2022, 6, 8, 0, 0)
    self.addCleanup(mock_datetime_patcher.stop)

  def _MockConnector(self, sub_module_name: str, mock_obj: mock.Mock):
    mock_patcher = mock.patch(
        f'cros.factory.bundle_creator.connector.{sub_module_name}')
    mock_connector = mock_patcher.start()
    mock_connector.return_value = mock_obj
    self.addCleanup(mock_patcher.stop)

  def _PublishCreateBundleMessage(self):
    self._pubsub_connector.PublishMessage(self._TOPIC_NAME,
                                          self._message.SerializeToString())
    sleep(1)  # Ensure the message is published.

  def _ReadManifest(self) -> Dict:
    manifest_path = os.path.join(self._temp_dir_path, 'MANIFEST.yaml')
    return yaml.safe_load(file_utils.ReadFile(manifest_path))


if __name__ == '__main__':
  unittest.main()