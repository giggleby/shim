# Copyright 2023 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

from dataclasses import dataclass
import os


# isort: split

from cros.factory.bundle_creator.connector import cloudtasks_connector
from cros.factory.bundle_creator.connector import hwid_api_connector
from cros.factory.bundle_creator.connector import pubsub_connector
from cros.factory.bundle_creator.docker import config
from cros.factory.bundle_creator.docker import worker
from cros.factory.bundle_creator.proto import factorybundle_pb2  # pylint: disable=no-name-in-module
from cros.factory.bundle_creator.proto import factorybundle_v2_pb2  # pylint: disable=no-name-in-module
from cros.factory.utils import file_utils
from cros.factory.utils import json_utils
from cros.factory.utils import process_utils


FW_INFO_FILE = 'firmware_info.json'


class ExtractFirmwareInfoError(Exception):
  pass


@dataclass
class ExtractFirmwareInfoTask(worker.IWorkerTask):
  """A placeholder represents the information of an extract firmware info task.

  Properties:
    project: The project name.
    phase: The phase name.
    image_gs_path: The image path on Google Storage to be processed.
    email: The email of the requester.
    bug_number: The bug number to create a HWID CL.
  """
  project: str
  phase: str
  image_gs_path: str
  email: str
  bug_number: int

  @classmethod
  def FromPubSubMessage(cls, pubsub_message: pubsub_connector.PubSubMessage):
    message = factorybundle_v2_pb2.ExtractFirmwareInfoRequest.FromString(
        pubsub_message.data)
    return cls(project=message.project, phase=message.phase,
               image_gs_path=message.image_gs_path, email=message.email,
               bug_number=message.bug_number)

  def ToOriginalRequest(self):
    message = factorybundle_pb2.ExtractFirmwareInfoRpcRequest()
    message.project = self.project
    message.phase = self.phase
    message.image_gs_path = self.image_gs_path
    message.email = self.email
    message.bug_number = self.bug_number
    return message


class FirmwareInfoExtractor(worker.BaseWorker):
  """Firmware Info Extractor"""

  WORKER_TASK = ExtractFirmwareInfoTask
  SUBSCRIPTION_ID = config.FW_INFO_EXTRACTOR_SUBSCRIPTION

  def __init__(self):
    super().__init__()
    self._cloudtasks_connector = cloudtasks_connector.CloudTasksConnector(
        config.GCLOUD_PROJECT)
    self._hwid_api_connector = hwid_api_connector.HWIDAPIConnector(
        config.HWID_API_ENDPOINT)
    self._pubsub_connector = pubsub_connector.PubSubConnector(
        config.GCLOUD_PROJECT)

  def TryProcessRequest(self):
    """See base class."""
    task = self._PullTask()
    if task:
      extractor_result = factorybundle_pb2.FirmwareInfoExtractorResult()
      extractor_result.original_request.MergeFrom(task.ToOriginalRequest())
      try:
        cl_url = self._ExtractFirmwareInfo(task)
        extractor_result.cl_url.extend(cl_url)
        extractor_result.status = (
            factorybundle_pb2.FirmwareInfoExtractorResult.Status.NO_ERROR)
      except ExtractFirmwareInfoError as e:
        extractor_result.error_message = str(e)
        extractor_result.status = (
            factorybundle_pb2.FirmwareInfoExtractorResult.Status.FAILED)
      self._cloudtasks_connector.ResponseFirmwareInfoExtractorResult(
          extractor_result)

  def _LogAndCheckOutput(self, cmd):
    try:
      output = process_utils.LogAndCheckOutput(cmd, stderr=process_utils.STDOUT)
      self._logger.info(output)
    except process_utils.CalledProcessError as e:
      raise ExtractFirmwareInfoError(e.stdout) from None

  def _ExtractFirmwareInfo(self, task: ExtractFirmwareInfoTask):
    self._logger.info(task)

    image_gs_path = task.image_gs_path

    # Try to find archive anyway to speed up the process. If no archive, use
    # raw binary instead.
    if not image_gs_path.endswith('.zip'):
      image_gs_path += '.zip'

    # The path should follow the pattern:
    # chromeos-releases/{$CHANNEL}/{$BOARD}/{$VERSION}/{$IMAGE_NAME}.bin(.zip)?
    try:
      _, _, board, _, image_file = image_gs_path.split('/')
    except ValueError:
      raise ExtractFirmwareInfoError(
          f'Invalid image path: {task.image_gs_path}') from None

    with file_utils.TempDirectory() as temp_dir:
      os.chdir(temp_dir)

      try:
        self._LogAndCheckOutput(['gsutil', 'cp', f'gs://{image_gs_path}', '.'])
        self._LogAndCheckOutput(['unzip', image_file])
      except ExtractFirmwareInfoError:
        self._logger.warning(
            'Cannot find image archive. Try to find raw binary image.')
        self._LogAndCheckOutput(
            ['gsutil', 'cp', f'gs://{image_gs_path[:-4]}', '.'])
      image_file = image_file[:-4]

      self._LogAndCheckOutput([
          '/usr/local/factory/factory.par', 'extract_firmware_info', image_file,
          '--projects', task.project, '--output', FW_INFO_FILE
      ])

      fw_info = json_utils.LoadFile(FW_INFO_FILE)
      fw_info['board'] = board

      self._logger.info(fw_info)

      fw_info = json_utils.DumpStr(fw_info)
      cl_url = []
      description = f'Firmware info extracted from {image_file}'
      try:
        cl_url += self._hwid_api_connector.CreateHWIDFirmwareInfoCL(
            fw_info, task.email, task.bug_number, task.phase, description)
      except hwid_api_connector.HWIDAPIRequestException as e:
        error_msg = str(e)
        self._logger.error(error_msg)
        raise ExtractFirmwareInfoError(error_msg) from None

    return cl_url
