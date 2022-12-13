# Copyright 2017 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

import base64
from dataclasses import dataclass
from datetime import datetime
import logging
import os
import time
from typing import List, Optional, Tuple

from google.cloud import logging as gc_logging
import yaml


# isort: split

from cros.factory.bundle_creator.connector import cloudtasks_connector
from cros.factory.bundle_creator.connector import firestore_connector
from cros.factory.bundle_creator.connector import hwid_api_connector
from cros.factory.bundle_creator.connector import pubsub_connector
from cros.factory.bundle_creator.connector import storage_connector
from cros.factory.bundle_creator.docker import config
from cros.factory.bundle_creator.proto import factorybundle_pb2  # pylint: disable=no-name-in-module
from cros.factory.bundle_creator.proto import factorybundle_v2_pb2  # pylint: disable=no-name-in-module
from cros.factory.utils import file_utils
from cros.factory.utils import process_utils


class CreateBundleException(Exception):
  """An Exception raised when fail to create factory bundle."""


@dataclass
class CreateBundleTask:
  """A placeholder represents the information of a create bundle task.

  Properties:
    doc_id: The document id of the corresponding request document stored in
        Cloud Firestore.
    email: The email of the bundle creator.
    board: The board name.
    project: The project name.
    phase: The phase name.
    toolkit_version: The toolkit version.
    test_image_version: The test image version.
    release_image_version: The release image version.
    update_hwid_db_firmware_info: A boolean value which represents including
        firmware info in HWID DB or not.
    firmware_source: The firmware source, `None` if it isn't set.
    hwid_related_bug_number: The bug number to create a HWID CL, `None` if it
        isn't set.
  """
  doc_id: str
  email: str
  board: str
  project: str
  phase: str
  toolkit_version: str
  test_image_version: str
  release_image_version: str
  update_hwid_db_firmware_info: bool
  firmware_source: Optional[str] = None
  hwid_related_bug_number: Optional[int] = None

  @classmethod
  def FromPubSubMessage(
      cls,
      pubsub_message: pubsub_connector.PubSubMessage) -> 'CreateBundleTask':
    if pubsub_message.attributes.get('request_from') == 'v2':
      message = factorybundle_v2_pb2.CreateBundleMessage.FromString(
          pubsub_message.data)
      metadata = message.request.bundle_metadata
      hwid_option = message.request.hwid_option
      return cls(
          doc_id=message.doc_id, email=message.request.email,
          board=metadata.board, project=metadata.project, phase=metadata.phase,
          toolkit_version=metadata.toolkit_version,
          test_image_version=metadata.test_image_version,
          release_image_version=metadata.release_image_version,
          update_hwid_db_firmware_info=hwid_option.update_db_firmware_info,
          firmware_source=metadata.firmware_source or None,
          hwid_related_bug_number=hwid_option.related_bug_number or None)

    message = factorybundle_pb2.CreateBundleMessage.FromString(
        pubsub_message.data)
    request = message.request
    task = cls(
        doc_id=message.doc_id, email=request.email, board=request.board,
        project=request.project, phase=request.phase,
        toolkit_version=request.toolkit_version,
        test_image_version=request.test_image_version,
        release_image_version=request.release_image_version,
        update_hwid_db_firmware_info=request.update_hwid_db_firmware_info)
    task.firmware_source = request.firmware_source if request.HasField(
        'firmware_source') else None
    task.hwid_related_bug_number = (
        request.hwid_related_bug_number
        if request.HasField('hwid_related_bug_number') else None)
    return task

  def ToOriginalRequest(self) -> factorybundle_pb2.CreateBundleRpcRequest:
    request = factorybundle_pb2.CreateBundleRpcRequest()
    request.board = self.board
    request.project = self.project
    request.phase = self.phase
    request.toolkit_version = self.toolkit_version
    request.test_image_version = self.test_image_version
    request.release_image_version = self.release_image_version
    request.email = self.email
    request.update_hwid_db_firmware_info = self.update_hwid_db_firmware_info
    if self.firmware_source:
      request.firmware_source = self.firmware_source
    if self.hwid_related_bug_number:
      request.hwid_related_bug_number = self.hwid_related_bug_number
    return request

  def ToStorageBundleMetadata(self) -> storage_connector.StorageBundleMetadata:
    return storage_connector.StorageBundleMetadata(
        doc_id=self.doc_id, email=self.email, board=self.board,
        project=self.project, phase=self.phase,
        toolkit_version=self.toolkit_version,
        test_image_version=self.test_image_version,
        release_image_version=self.release_image_version,
        firmware_source=self.firmware_source or None)


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
    task = self._PullTask()
    if task:
      try:
        self._firestore_connector.UpdateUserRequestStatus(
            task.doc_id, firestore_connector.UserRequestStatus.IN_PROGRESS)
        self._firestore_connector.UpdateUserRequestStartTime(task.doc_id)

        gs_path, cl_url, cl_error_msg = self._CreateBundle(task)

        self._firestore_connector.UpdateUserRequestStatus(
            task.doc_id, firestore_connector.UserRequestStatus.SUCCEEDED)
        self._firestore_connector.UpdateUserRequestEndTime(task.doc_id)
        self._firestore_connector.UpdateUserRequestGsPath(task.doc_id, gs_path)
        self._firestore_connector.UpdateHWIDCLURLAndErrorMessage(
            task.doc_id, cl_url, cl_error_msg)

        worker_result = factorybundle_pb2.WorkerResult()
        worker_result.status = factorybundle_pb2.WorkerResult.NO_ERROR
        worker_result.original_request.MergeFrom(task.ToOriginalRequest())
        worker_result.gs_path = gs_path
        worker_result.cl_url.extend(cl_url)
        if cl_error_msg:
          worker_result.status = (
              factorybundle_pb2.WorkerResult.CREATE_CL_FAILED)
          worker_result.error_message = str(cl_error_msg)
        self._cloudtasks_connector.ResponseWorkerResult(
            self._EncodeWorkerResult(worker_result))
      except CreateBundleException as e:
        self._logger.error(e)

        self._firestore_connector.UpdateUserRequestStatus(
            task.doc_id, firestore_connector.UserRequestStatus.FAILED)
        self._firestore_connector.UpdateUserRequestEndTime(task.doc_id)
        self._firestore_connector.UpdateUserRequestErrorMessage(
            task.doc_id, str(e))

        worker_result = factorybundle_pb2.WorkerResult()
        worker_result.status = factorybundle_pb2.WorkerResult.FAILED
        worker_result.original_request.MergeFrom(task.ToOriginalRequest())
        worker_result.error_message = str(e)
        self._cloudtasks_connector.ResponseWorkerResult(
            self._EncodeWorkerResult(worker_result))

  def _CreateBundle(
      self, task: CreateBundleTask) -> Tuple[str, List[str], Optional[str]]:
    """Creates a factory bundle with the specific manifest from a user.

    If `update_hwid_db_firmware_info` is set, this function will send request to
    HWID API server to create HWID DB change for firmware info.

    Args:
      task: A `CreateBundleTask` object fetched from a Pub/Sub subscription.

    Returns:
      A tuple of the following:
        - A string of the google storage path.
        - A list contains created HWID CL url.
        - A string of error message when requesting HWID API failed.

    Raises:
      CreateBundleException: If it fails to run `finalize_bundle` command.
    """
    self._logger.info(task)

    with file_utils.TempDirectory() as temp_dir:
      os.chdir(temp_dir)

      bundle_name = f'{datetime.now():%Y%m%d}_{task.phase}'
      firmware_source = ('release_image/' + task.firmware_source
                         if task.firmware_source else 'release_image')
      manifest = {
          'board': task.board,
          'project': task.project,
          # TODO(b/204853206): Add 'designs' to CreateBundleRpcRequest and
          # update UI.
          'designs': 'boxster_designs',
          'bundle_name': bundle_name,
          'toolkit': task.toolkit_version,
          'test_image': task.test_image_version,
          'release_image': task.release_image_version,
          'firmware': firmware_source,
      }
      has_firmware_setting = (
          self._firestore_connector.GetHasFirmwareSettingByProject(
              task.project))
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
      if task.update_hwid_db_firmware_info:
        finalize_bundle_command += ['--bundle-record', bundle_record_path]
      output = None
      try:
        output = process_utils.LogAndCheckOutput(finalize_bundle_command,
                                                 stderr=process_utils.STDOUT)
      except process_utils.CalledProcessError as e:
        raise CreateBundleException(e.stdout) from None
      self._logger.info(output)

      bundle_path = os.path.join(
          temp_dir, f'factory_bundle_{task.project}_{bundle_name}.tar.bz2')
      gs_path = self._storage_connector.UploadCreatedBundle(
          bundle_path, task.ToStorageBundleMetadata())

      cl_url = []
      cl_error_msg = None
      if task.update_hwid_db_firmware_info:
        bundle_record = file_utils.ReadFile(bundle_record_path)
        try:
          cl_url += self._hwid_api_connector.CreateHWIDFirmwareInfoCL(
              bundle_record, task.email, task.hwid_related_bug_number,
              task.phase)
        except hwid_api_connector.HWIDAPIRequestException as e:
          cl_error_msg = str(e)
          self._logger.error(cl_error_msg)

    return gs_path, cl_url, cl_error_msg

  def _PullTask(self) -> Optional[CreateBundleTask]:
    """Pulls one task from the Pub/Sub subscription.

    Returns:
      A `CreateBundleTask` object if it exists.  Otherwise `None` is returned.
    """
    message = self._pubsub_connector.PullFirstMessage(
        config.PUBSUB_SUBSCRIPTION)
    if message:
      return CreateBundleTask.FromPubSubMessage(message)
    return None

  def _EncodeWorkerResult(self,
                          worker_result: factorybundle_pb2.WorkerResult) -> str:
    return base64.b64encode(worker_result.SerializeToString()).decode('utf-8')


if __name__ == '__main__':
  if config.ENV_TYPE == 'local':
    logging.basicConfig(level=logging.INFO)
  else:
    gc_logging.Client().setup_logging(log_level=logging.INFO)
  worker = EasyBundleCreationWorker()
  worker.MainLoop()
