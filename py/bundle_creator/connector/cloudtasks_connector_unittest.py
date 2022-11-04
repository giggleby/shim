# Copyright 2022 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

import unittest
from unittest import mock

from googleapiclient.errors import HttpError

from cros.factory.bundle_creator.connector import cloudtasks_connector


class CloudTasksConnectorTest(unittest.TestCase):

  def setUp(self):
    self._mock_request = mock.Mock()
    self._mock_tasks = mock.Mock()
    self._mock_tasks.create.return_value = self._mock_request

    def _MockApiBuild(service_name: str, version: str,
                      cache_discovery: bool) -> mock.Mock:
      del cache_discovery
      if service_name == 'cloudtasks' and version == 'v2beta3':
        mock_service = mock.Mock()
        mock_service.projects().locations().queues().tasks.return_value = (
            self._mock_tasks)
        return mock_service
      raise ValueError(
          f'Service `{service_name}` with version `{version}` isn\'t supported.'
      )

    mock_build_patcher = mock.patch('googleapiclient.discovery.build')
    mock_api_build = mock_build_patcher.start()
    mock_api_build.side_effect = _MockApiBuild
    self.addCleanup(mock_build_patcher.stop)

    self._mock_logger = mock.Mock()
    mock_logging_patcher = mock.patch('logging.getLogger')
    mock_logger = mock_logging_patcher.start()
    mock_logger.return_value = self._mock_logger
    self.addCleanup(mock_logging_patcher.stop)

    self._connector = cloudtasks_connector.CloudTasksConnector(
        'fake-project-id')

  def testResponseWorkerResult_succeed_verifyRequest(self):
    encoded_worker_result = 'Ig5nczovL2Zha2VfcGF0aA=='

    self._connector.ResponseWorkerResult(encoded_worker_result)

    sent_data = self._mock_tasks.create.call_args.kwargs['body']['task'][
        'app_engine_http_request']['body']
    self.assertEqual(sent_data, encoded_worker_result)
    self._mock_request.execute.assert_called_once_with(num_retries=5)

  def testResponseWorkerResult_httpError_verifyLogError(self):
    http_error = HttpError(resp=mock.Mock(status=403), content=b'fake_content')
    self._mock_request.execute.side_effect = http_error

    self._connector.ResponseWorkerResult('fake_encoded_worker_result')

    self._mock_logger.error.assert_called_once_with(http_error)


if __name__ == '__main__':
  unittest.main()
