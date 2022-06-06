# Copyright 2017 The Chromium OS Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.
#
# TODO(b/214528226): Add a unit test for this file.

import datetime
import logging
import os
import time
from typing import List, Optional, Tuple

from google.cloud import logging as gc_logging
from google.protobuf import text_format
import yaml

from cros.factory.bundle_creator.connector import cloudtasks_connector
from cros.factory.bundle_creator.connector import firestore_connector
from cros.factory.bundle_creator.connector import hwid_api_connector
from cros.factory.bundle_creator.connector import pubsub_connector
from cros.factory.bundle_creator.connector import storage_connector
from cros.factory.bundle_creator.docker import config
from cros.factory.bundle_creator.proto import factorybundle_pb2  # pylint: disable=no-name-in-module
from cros.factory.utils import file_utils
from cros.factory.utils import process_utils


class CreateBundleException(Exception):
  """An Exception raised when fail to create factory bundle."""


class EasyBundleCreationWorker:
  """Easy Bundle Creation worker."""

  def __init__(self):
    self._logger = logging.getLogger('EasyBundleCreationWorker')
    self._cloudtasks_connector = cloudtasks_connector.CloudTasksConnector(
        config.GCLOUD_PROJECT)
    self._firestore_connector = firestore_connector.FirestoreConnector(
        config.GCLOUD_PROJECT)
    self._hwid_api_connector = hwid_api_connector.HWIDAPIConnector(
        config.HWID_API_ENDPOINT)
    self._pubsub_connector = pubsub_connector.PubSubConnector(
        config.GCLOUD_PROJECT)
    self._storage_connector = storage_connector.StorageConnector(
        config.GCLOUD_PROJECT, config.BUNDLE_BUCKET)

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

        gs_path, cl_url, cl_error_msg = self._CreateBundle(task_proto)

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
      except CreateBundleException as e:
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

  def _CreateBundle(
      self, create_bundle_message: factorybundle_pb2.CreateBundleMessage
  ) -> Tuple[str, List[str], Optional[str]]:
    """Creates a factory bundle with the specific manifest from a user.

    If `update_hwid_db_firmware_info` is set, this function will send request to
    HWID API server to create HWID DB change for firmware info.

    Args:
      create_bundle_message: A CreateBundleMessage proto message fetched
          from a Pub/Sub subscription.

    Returns:
      A tuple of the following:
        - A string of the google storage path.
        - A list contains created HWID CL url.
        - A string of error message when requesting HWID API failed.

    Raises:
      CreateBundleException: If it fails to run `finalize_bundle` command.
    """
    request = create_bundle_message.request
    self._logger.info(
        text_format.MessageToString(request, as_utf8=True, as_one_line=True))

    with file_utils.TempDirectory() as temp_dir:
      os.chdir(temp_dir)

      bundle_name = '{:%Y%m%d}_{}'.format(datetime.datetime.now(),
                                          request.phase)
      firmware_source = ('release_image/' + request.firmware_source
                         if request.HasField('firmware_source') else
                         'release_image')
      manifest = {
          'board': request.board,
          'project': request.project,
          # TODO(b/204853206): Add 'designs' to CreateBundleRpcRequest and
          # update UI.
          'designs': 'boxster_designs',
          'bundle_name': bundle_name,
          'toolkit': request.toolkit_version,
          'test_image': request.test_image_version,
          'release_image': request.release_image_version,
          'firmware': firmware_source,
      }
      has_firmware_setting = (
          self._firestore_connector.GetHasFirmwareSettingByProject(
              request.project))
      if has_firmware_setting:
        manifest['has_firmware'] = has_firmware_setting
      with open(os.path.join(temp_dir, 'MANIFEST.yaml'), 'w',
                encoding='utf8') as f:
        yaml.safe_dump(manifest, f)

      finalize_bundle_command = [
          '/usr/local/factory/factory.par', 'finalize_bundle',
          os.path.join(temp_dir, 'MANIFEST.yaml'), '--jobs', '7'
      ]
      bundle_record_path = os.path.join(temp_dir, 'bundle_record.json')
      if request.update_hwid_db_firmware_info:
        finalize_bundle_command += ['--bundle-record', bundle_record_path]
      output = None
      try:
        output = process_utils.LogAndCheckOutput(finalize_bundle_command,
                                                 stderr=process_utils.STDOUT)
      except process_utils.CalledProcessError as e:
        raise CreateBundleException(e.stdout) from None
      self._logger.info(output)

      bundle_path = os.path.join(
          temp_dir, 'factory_bundle_{}_{}.tar.bz2'.format(
              request.project, bundle_name))
      gs_path = self._storage_connector.UploadCreatedBundle(
          bundle_path, create_bundle_message)

      cl_url = []
      cl_error_msg = None
      if request.update_hwid_db_firmware_info:
        bundle_record = file_utils.ReadFile(bundle_record_path)
        try:
          cl_url += self._hwid_api_connector.CreateHWIDFirmwareInfoCL(
              bundle_record, request.email)
        except hwid_api_connector.HWIDAPIRequestException as e:
          cl_error_msg = str(e)
          self._logger.error(cl_error_msg)

    return gs_path, cl_url, cl_error_msg

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
  if config.ENV_TYPE == 'local':
    logging.basicConfig(level=logging.INFO)
  else:
    gc_logging.Client().setup_logging(log_level=logging.INFO)
  worker = EasyBundleCreationWorker()
  worker.MainLoop()
