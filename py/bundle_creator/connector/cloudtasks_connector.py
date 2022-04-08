# Copyright 2022 The Chromium OS Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

import base64
import logging

from googleapiclient import discovery  # pylint: disable=import-error
from googleapiclient.errors import HttpError  # pylint: disable=import-error

from cros.factory.bundle_creator.proto import factorybundle_pb2  # pylint: disable=no-name-in-module


class CloudTasksConnector:
  """Connector for accessing the Cloud Tasks service."""

  _CLOUD_MAIL_ROUTING_NAME = 'cloud-mail'
  _RESPONSE_CALLBACK_URI = '/_ah/stubby/FactoryBundleService.ResponseCallback'
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
      worker_result: A worker result proto message.
    """
    request_body = {
        'task': {
            'app_engine_http_request': {
                'http_method':
                    'POST',
                'app_engine_routing': {
                    'service': self._CLOUD_MAIL_ROUTING_NAME,
                },
                'relative_uri':
                    self._RESPONSE_CALLBACK_URI,
                'body':
                    base64.b64encode(
                        worker_result.SerializeToString()).decode('utf-8'),
            },
        },
    }
    try:
      request = self._tasks.create(parent=self._queue_name, body=request_body)
      request.execute(num_retries=self._MAX_RETRY)
    except HttpError as e:
      self._logger.error(e)
