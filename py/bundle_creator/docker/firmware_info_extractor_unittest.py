# Copyright 2023 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

import os
import tempfile
import unittest
from unittest import mock

from cros.factory.bundle_creator.connector import hwid_api_connector
from cros.factory.bundle_creator.connector import pubsub_connector
from cros.factory.bundle_creator.docker import firmware_info_extractor
from cros.factory.bundle_creator.proto import factorybundle_pb2  # pylint: disable=no-name-in-module
from cros.factory.bundle_creator.proto import factorybundle_v2_pb2  # pylint: disable=no-name-in-module
from cros.factory.utils import json_utils
from cros.factory.utils import process_utils


class ExtractFirmwareInfoTaskTest(unittest.TestCase):

  def setUp(self):
    kwargs = {
        'project': 'proj',
        'phase': 'EVT',
        'image_gs_path': 'fake_path',
        'email': 'foo@bar',
        'bug_number': 123
    }
    self._request = factorybundle_pb2.ExtractFirmwareInfoRpcRequest(**kwargs)
    self._v2_request = factorybundle_v2_pb2.ExtractFirmwareInfoRequest(**kwargs)
    self._task = firmware_info_extractor.ExtractFirmwareInfoTask(**kwargs)

  def testFromPubSubMessage_succeed(self):
    pubsub_message = pubsub_connector.PubSubMessage(
        data=self._v2_request.SerializeToString(), attributes={})

    task = firmware_info_extractor.ExtractFirmwareInfoTask.FromPubSubMessage(
        pubsub_message)

    self.assertEqual(task, self._task)

  def testToOriginalRequest_succeed(self):
    request = self._task.ToOriginalRequest()

    self.assertEqual(request, self._request)


class FirmwareInfoExtractorTest(unittest.TestCase):

  def setUp(self):
    self._temp_dir_path = tempfile.mkdtemp()
    patcher = mock.patch('cros.factory.utils.file_utils.TempDirectory')
    mock_temp_dir = patcher.start()
    mock_temp_dir.return_value.__enter__.return_value = self._temp_dir_path
    self.addCleanup(patcher.stop)

    mock_check_output_patcher = mock.patch(
        'cros.factory.utils.process_utils.LogAndCheckOutput')
    self._mock_check_output = mock_check_output_patcher.start()
    self.addCleanup(mock_check_output_patcher.stop)

    self._mock_cloudtasks_connector = mock.Mock()
    self._mock_hwid_api_connector = mock.Mock()
    self._mock_pubsub_connector = mock.Mock()
    self._MockConnector('cloudtasks_connector.CloudTasksConnector',
                        self._mock_cloudtasks_connector)
    self._MockConnector('hwid_api_connector.HWIDAPIConnector',
                        self._mock_hwid_api_connector)
    self._MockConnector('pubsub_connector.PubSubConnector',
                        self._mock_pubsub_connector)

    self.extractor = firmware_info_extractor.FirmwareInfoExtractor()

  def testTryProcessRequest_emptyTask(self):
    self._mock_pubsub_connector.PullFirstMessage.return_value = None

    self.extractor.TryProcessRequest()

    fn = self._mock_cloudtasks_connector.ResponseFirmwareInfoExtractorResult
    fn.assert_not_called()

  def testTryProcessRequest_succeed_verifiesCallConnectors(self):
    self._CreateFakeFirmwareInfo({})
    self._mock_hwid_api_connector.CreateHWIDFirmwareInfoCL.return_value = [
        'fake_url'
    ]
    task = self._PublishFakeTask()

    self.extractor.TryProcessRequest()

    expected_result = factorybundle_pb2.FirmwareInfoExtractorResult()
    expected_result.original_request.MergeFrom(task.ToOriginalRequest())
    expected_result.status = (
        factorybundle_pb2.FirmwareInfoExtractorResult.Status.NO_ERROR)
    expected_result.cl_url.append('fake_url')
    fn = self._mock_cloudtasks_connector.ResponseFirmwareInfoExtractorResult
    fn.assert_called_once_with(expected_result)
    fn = self._mock_hwid_api_connector.CreateHWIDFirmwareInfoCL
    fn.assert_called_once_with('{"board": "board"}', 'foo@bar', 123, 'evt',
                               'Firmware info extracted from image')

  def testTryProcessRequest_HWIDAPIError_verifiesErrorMessage(self):
    self._CreateFakeFirmwareInfo({})
    self._mock_hwid_api_connector.CreateHWIDFirmwareInfoCL.side_effect = (
        hwid_api_connector.HWIDAPIRequestException('fake error'))
    task = self._PublishFakeTask()

    self.extractor.TryProcessRequest()

    expected_result = factorybundle_pb2.FirmwareInfoExtractorResult()
    expected_result.original_request.MergeFrom(task.ToOriginalRequest())
    expected_result.error_message = 'fake error'
    expected_result.status = (
        factorybundle_pb2.FirmwareInfoExtractorResult.Status.FAILED)
    fn = self._mock_cloudtasks_connector.ResponseFirmwareInfoExtractorResult
    fn.assert_called_once_with(expected_result)

  def testTryProcessRequest_callProcessError_verifiesErrorMessage(self):
    self._mock_check_output.side_effect = process_utils.CalledProcessError(
        1, 'fake_cmd', 'fake error')
    task = self._PublishFakeTask()

    self.extractor.TryProcessRequest()

    expected_result = factorybundle_pb2.FirmwareInfoExtractorResult()
    expected_result.original_request.MergeFrom(task.ToOriginalRequest())
    expected_result.error_message = 'fake error'
    expected_result.status = (
        factorybundle_pb2.FirmwareInfoExtractorResult.Status.FAILED)
    fn = self._mock_cloudtasks_connector.ResponseFirmwareInfoExtractorResult
    fn.assert_called_once_with(expected_result)

  def testTryProcessRequest_invalidImagePath_verifiesErrorMessage(self):
    task = self._PublishFakeTask(image_gs_path='invalid_path')

    self.extractor.TryProcessRequest()

    expected_result = factorybundle_pb2.FirmwareInfoExtractorResult()
    expected_result.original_request.MergeFrom(task.ToOriginalRequest())
    expected_result.error_message = 'Invalid image path: invalid_path'
    expected_result.status = (
        factorybundle_pb2.FirmwareInfoExtractorResult.Status.FAILED)
    fn = self._mock_cloudtasks_connector.ResponseFirmwareInfoExtractorResult
    fn.assert_called_once_with(expected_result)

  def testTryProcessRequest_noArchive_downloadRawImage(self):
    self._CreateFakeFirmwareInfo({})
    self._mock_hwid_api_connector.CreateHWIDFirmwareInfoCL.return_value = [
        'fake_url'
    ]

    def _MockCheckOutput(cmd, *unused_arg, **unused_kwargs):
      if cmd[2].endswith('.zip'):
        raise process_utils.CalledProcessError(1, 'fake_cmd', 'no image found')

    self._PublishFakeTask(image_gs_path='_/_/board/_/image.bin')
    self._mock_check_output.side_effect = _MockCheckOutput

    self.extractor.TryProcessRequest()

    self.assertEqual(3, len(self._mock_check_output.call_args_list))
    self.assertEqual(self._mock_check_output.call_args_list[0].args[0],
                     ['gsutil', 'cp', 'gs://_/_/board/_/image.bin.zip', '.'])
    self.assertEqual(self._mock_check_output.call_args_list[1].args[0],
                     ['gsutil', 'cp', 'gs://_/_/board/_/image.bin', '.'])

  def _CreateFakeFirmwareInfo(self, fw_info):
    json_utils.DumpFile(
        os.path.join(self._temp_dir_path, 'firmware_info.json'), fw_info)

  def _PublishFakeTask(self, project='proj', phase='evt',
                       image_gs_path='_/_/board/_/image.zip', email='foo@bar',
                       bug_number=123):
    """Publishes a fake task to mocked PubSubConnector and returns the task."""
    request = factorybundle_v2_pb2.ExtractFirmwareInfoRequest(
        project=project, phase=phase, image_gs_path=image_gs_path, email=email,
        bug_number=bug_number)
    pubsub_message = pubsub_connector.PubSubMessage(
        data=request.SerializeToString(), attributes={})
    self._mock_pubsub_connector.PullFirstMessage.return_value = pubsub_message
    return firmware_info_extractor.ExtractFirmwareInfoTask.FromPubSubMessage(
        pubsub_message)

  def _MockConnector(self, sub_module_name: str, mock_obj: mock.Mock):
    mock_patcher = mock.patch(
        f'cros.factory.bundle_creator.connector.{sub_module_name}')
    mock_connector = mock_patcher.start()
    mock_connector.return_value = mock_obj
    self.addCleanup(mock_patcher.stop)


if __name__ == '__main__':
  unittest.main()
