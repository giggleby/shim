# Copyright 2017 The Chromium OS Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.
#
# TODO(b/214528226): Add a unit test for this file.

import logging
import time
from typing import Optional

from cros.factory.bundle_creator.connector import cloudtasks_connector
from cros.factory.bundle_creator.connector import firestore_connector
from cros.factory.bundle_creator.connector import pubsub_connector
from cros.factory.bundle_creator.docker import config
from cros.factory.bundle_creator.docker import util
from cros.factory.bundle_creator.proto import factorybundle_pb2  # pylint: disable=no-name-in-module


class EasyBundleCreationWorker:
  """Easy Bundle Creation worker."""

  def __init__(self):
    self._logger = logging.getLogger('EasyBundleCreationWorker')
    self._cloudtasks_connector = cloudtasks_connector.CloudTasksConnector(
        config.GCLOUD_PROJECT)
    self._firestore_connector = firestore_connector.FirestoreConnector(
        config.GCLOUD_PROJECT)
    self._pubsub_connector = pubsub_connector.PubSubConnector(
        config.GCLOUD_PROJECT)

  def MainLoop(self):
    """The main loop tries to process a request per 30 seconds."""
    while True:
      try:
        worker.TryProcessRequest()
      except Exception as e:
        self._logger.error(e)
      time.sleep(30)

  def TryProcessRequest(self):
    """Tries to pull the first task and process the request."""
    task_proto = self._PullTask()
    if task_proto:
      try:
        self._firestore_connector.UpdateUserRequestStatus(
            task_proto.doc_id,
            self._firestore_connector.USER_REQUEST_STATUS_IN_PROGRESS)
        self._firestore_connector.UpdateUserRequestStartTime(task_proto.doc_id)

        gs_path, cl_url, cl_error_msg = util.CreateBundle(task_proto)

        self._firestore_connector.UpdateUserRequestStatus(
            task_proto.doc_id,
            self._firestore_connector.USER_REQUEST_STATUS_SUCCEEDED)
        self._firestore_connector.UpdateUserRequestEndTime(task_proto.doc_id)
        self._firestore_connector.UpdateUserRequestGsPath(
            task_proto.doc_id, gs_path)

        worker_result = factorybundle_pb2.WorkerResult()
        worker_result.status = factorybundle_pb2.WorkerResult.NO_ERROR
        worker_result.original_request.MergeFrom(task_proto.request)
        worker_result.gs_path = gs_path
        worker_result.cl_url.extend(cl_url)
        if cl_error_msg:
          worker_result.status = (
              factorybundle_pb2.WorkerResult.CREATE_CL_FAILED)
          worker_result.error_message = str(cl_error_msg)
        self._cloudtasks_connector.ResponseWorkerResult(worker_result)
      except util.CreateBundleException as e:
        self._logger.error(e)

        self._firestore_connector.UpdateUserRequestStatus(
            task_proto.doc_id,
            self._firestore_connector.USER_REQUEST_STATUS_FAILED)
        self._firestore_connector.UpdateUserRequestEndTime(task_proto.doc_id)
        self._firestore_connector.UpdateUserRequestErrorMessage(
            task_proto.doc_id, str(e))

        worker_result = factorybundle_pb2.WorkerResult()
        worker_result.status = factorybundle_pb2.WorkerResult.FAILED
        worker_result.original_request.MergeFrom(task_proto.request)
        worker_result.error_message = str(e)
        self._cloudtasks_connector.ResponseWorkerResult(worker_result)

  def _PullTask(self) -> Optional[factorybundle_pb2.CreateBundleMessage]:
    """Pulls one task from the Pub/Sub subscription.

    Returns:
      A CreateBundleMessage proto message if it exists.  Otherwise `None` is
      returned.
    """
    message_data = self._pubsub_connector.PullFirstMessage(
        config.PUBSUB_SUBSCRIPTION)
    if message_data:
      return factorybundle_pb2.CreateBundleMessage.FromString(message_data)
    return None


if __name__ == '__main__':
  logging.basicConfig(level=logging.INFO)
  worker = EasyBundleCreationWorker()
  worker.MainLoop()
