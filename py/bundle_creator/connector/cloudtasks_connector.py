# Copyright 2022 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

import base64
import logging

from google.protobuf import any_pb2
from googleapiclient import discovery
from googleapiclient.errors import HttpError

from cros.factory.bundle_creator.proto import factorybundle_pb2  # pylint: disable=no-name-in-module


def EncodeMessage(message: any_pb2.Any) -> str:
  return base64.b64encode(message.SerializeToString()).decode('utf-8')


class CloudTasksConnector:
  """Connector for accessing the Cloud Tasks service."""

  _CLOUD_MAIL_ROUTING_NAME = 'cloud-mail'
  _SERVICE_URI = '/_ah/stubby/FactoryBundleService'
  _MAX_RETRY = 5

  def __init__(self, cloud_project_id: str):
    """Initializes a Cloud Tasks client by the cloud project id.

    Args:
      cloud_project_id: A cloud project id.
    """
    self._logger = logging.getLogger('CloudTasksConnector')
    self._queue_name = (f'projects/{cloud_project_id}'
                        '/locations/us-central1/queues/bundle-tasks-result')
    service = discovery.build('cloudtasks', 'v2beta3', cache_discovery=False)
    self._tasks = service.projects().locations().queues().tasks()

  def ResponseWorkerResult(self, worker_result: factorybundle_pb2.WorkerResult):
    """Creates a task to send the worker result.

    Args:
      worker_result: WorkerResult message.
    """
    self._SendRPCReqeust(EncodeMessage(worker_result), 'ResponseCallback')

  def ResponseFirmwareInfoExtractorResult(
      self, extractor_result: factorybundle_pb2.FirmwareInfoExtractorResult):
    """Creates a task to send the firmware info extractor result.

    Args:
      extractor_result: The FirmwareInfoExtractorResult message.
    """
    self._SendRPCReqeust(
        EncodeMessage(extractor_result), 'ExtractFirmwareInfoCallback')

  def _SendRPCReqeust(self, encoded_message: str, rpc_name: str):
    request_body = {
        'task': {
            'app_engine_http_request': {
                'http_method': 'POST',
                'app_engine_routing': {
                    'service': self._CLOUD_MAIL_ROUTING_NAME,
                },
                'relative_uri': f'{self._SERVICE_URI}.{rpc_name}',
                'body': encoded_message,
            },
        },
    }
    try:
      request = self._tasks.create(parent=self._queue_name, body=request_body)
      request.execute(num_retries=self._MAX_RETRY)
    except HttpError as e:
      self._logger.error(e)
