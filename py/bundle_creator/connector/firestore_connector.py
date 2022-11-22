# Copyright 2020 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

from dataclasses import asdict
from dataclasses import dataclass
from datetime import datetime
import logging
from typing import Any, Dict, List, Optional

from google.cloud import firestore


# isort: split

from cros.factory.bundle_creator.proto import factorybundle_pb2  # pylint: disable=no-name-in-module
from cros.factory.bundle_creator.proto import factorybundle_v2_pb2  # pylint: disable=no-name-in-module


@dataclass
class CreateBundleRequestInfo:
  """A placeholder represents the information of a create bundle request.

  Properties:
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
  def FromCreateBundleRpcRequest(
      cls, request: factorybundle_pb2.CreateBundleRpcRequest
  ) -> 'CreateBundleRequestInfo':
    info = cls(
        email=request.email, board=request.board, project=request.project,
        phase=request.phase, toolkit_version=request.toolkit_version,
        test_image_version=request.test_image_version,
        release_image_version=request.release_image_version,
        update_hwid_db_firmware_info=request.update_hwid_db_firmware_info)
    info.firmware_source = request.firmware_source if request.HasField(
        'firmware_source') else None
    info.hwid_related_bug_number = (
        request.hwid_related_bug_number
        if request.HasField('hwid_related_bug_number') else None)
    return info

  @classmethod
  def FromV2CreateBundleRequest(
      cls, request: factorybundle_v2_pb2.CreateBundleRequest
  ) -> 'CreateBundleRequestInfo':
    metadata = request.bundle_metadata
    hwid_option = request.hwid_option
    info = cls(email=request.email, board=metadata.board,
               project=metadata.project, phase=metadata.phase,
               toolkit_version=metadata.toolkit_version,
               test_image_version=metadata.test_image_version,
               release_image_version=metadata.release_image_version,
               update_hwid_db_firmware_info=hwid_option.update_db_firmware_info,
               firmware_source=metadata.firmware_source or None,
               hwid_related_bug_number=hwid_option.related_bug_number or None)
    return info


class FirestoreConnector:
  """The connector for accessing the Cloud Firestore database."""

  _COLLECTION_HAS_FIRMWARE_SETTINGS = 'has_firmware_settings'
  _COLLECTION_USER_REQUESTS = 'user_requests'

  USER_REQUEST_STATUS_NOT_STARTED = 'NOT_STARTED'
  USER_REQUEST_STATUS_IN_PROGRESS = 'IN_PROGRESS'
  USER_REQUEST_STATUS_SUCCEEDED = 'SUCCEEDED'
  USER_REQUEST_STATUS_FAILED = 'FAILED'

  def __init__(self, cloud_project_id: str):
    """Initializes the firestore client by a cloud project id.

    Args:
      cloud_project_id: A cloud project id.
    """
    self._logger = logging.getLogger('FirestoreConnector')
    self._client = firestore.Client(project=cloud_project_id)
    self._user_request_col_ref = self._client.collection(
        self._COLLECTION_USER_REQUESTS)

  def GetHasFirmwareSettingByProject(self, project: str) -> Optional[List[str]]:
    """Gets the `has_firmware` setting by a project name.

    Args:
      project: The project name as the document id.

    Returns:
      An array contains the firmware names if it exists.  Otherwise `None` is
      returned.
    """
    doc = self._client.collection(
        self._COLLECTION_HAS_FIRMWARE_SETTINGS).document(project).get()
    if doc.exists:
      try:
        return doc.get('has_firmware')
      except KeyError:
        self._logger.error(
            'No `has_firmware` attribute found in the existing document.')
    return None

  def CreateUserRequest(self, info: CreateBundleRequestInfo,
                        request_from: Optional[str] = None) -> str:
    """Creates a user request from the create bundle request.

    Args:
      info: A `CreateBundleRequestInfo` object which contains the information to
          create a user request document.
      request_from: An optional field to record where the request is from.

    Returns:
      A hashed document id generated from the created document.
    """
    doc_value = asdict(info)
    doc_value['status'] = self.USER_REQUEST_STATUS_NOT_STARTED
    doc_value['request_time'] = datetime.now()
    if not doc_value['firmware_source']:
      del doc_value['firmware_source']
    if not info.update_hwid_db_firmware_info:
      del doc_value['hwid_related_bug_number']
    if request_from:
      doc_value['request_from'] = request_from

    doc_ref = self._GetUserRequestDocRef()
    doc_ref.set(doc_value)
    return doc_ref.id

  def UpdateUserRequestStatus(self, doc_id: str, status: str):
    """Updates `status` of the specific user request document.

    Args:
      doc_id: The document id of the document to be updated.
      status: The value used to update.
    """
    self._TryUpdateUserRequestDocRef(doc_id, {'status': status})

  def UpdateUserRequestStartTime(self, doc_id: str):
    """Updates `start_time` of the specific user request document.

    Args:
      doc_id: The document id of the document to be updated.
    """
    self._UpdateUserRequestWithCurrentTime(doc_id, 'start_time')

  def UpdateUserRequestEndTime(self, doc_id: str):
    """Updates `end_time` of the specific user request document.

    Args:
      doc_id: The document id of the document to be updated.
    """
    self._UpdateUserRequestWithCurrentTime(doc_id, 'end_time')

  def UpdateUserRequestErrorMessage(self, doc_id: str, error_msg: str):
    """Updates an error message to the specific user request document.

    Args:
      doc_id: The document id of the document to be updated.
      error_msg: The string value used to update.
    """
    self._TryUpdateUserRequestDocRef(doc_id, {'error_message': error_msg})

  def UpdateUserRequestGsPath(self, doc_id: str, gs_path: str):
    """Updates a created bundle's gs path to the specific user request document.

    Args:
      doc_id: The document id of the document to be updated.
      gs_path: The path of the created bundle.
    """
    self._TryUpdateUserRequestDocRef(doc_id, {'gs_path': gs_path})

  def GetUserRequestsByEmail(self, email: str) -> List[Dict]:
    """Returns user requests with the specific email.

    Args:
      email: The requestor's email.

    Returns:
      A list of dictionaries which represent the specific user requests in
      descending order of `request_time`.
    """
    return [
        doc.to_dict()
        for doc in self._user_request_col_ref.where('email', '==', email).
        order_by('request_time', direction=firestore.Query.DESCENDING).stream()
    ]

  def UpdateHWIDCLURLAndErrorMessage(self, doc_id: str, cl_url: List[str],
                                     cl_error_msg: Optional[str]):
    """Updates HWID CL information to the specific user request document.

    Updates the created HWID CL URLs if there is at least one.  And updates the
    error message if it isn't `None`.

    Args:
      doc_id: The document id of the document to be updated.
      cl_url: A list contains created HWID CL url.
      cl_error_msg: A string of error message if it fails to call the HWID API.
    """
    value = {}
    if cl_url:
      value['hwid_cl_url'] = cl_url
    if cl_error_msg:
      value['hwid_cl_error_msg'] = cl_error_msg
    if value:
      self._TryUpdateUserRequestDocRef(doc_id, value)

  def ClearCollection(self, collection_name: str):
    """Testing purpose.  Deletes all documents in the specific collection.

    Args:
      collection_name: The name of the collection to be cleared.
    """
    col_ref = self._client.collection(collection_name)
    for doc_ref in col_ref.list_documents():
      doc_ref.delete()

  def GetUserRequestDocument(self, doc_id: str) -> Dict[str, Any]:
    """Testing purpose.  Gets the specific document.

    Args:
      doc_id: The document id of the document to be fetched.
    """
    return self._GetUserRequestDocRef(doc_id).get().to_dict()

  def _UpdateUserRequestWithCurrentTime(self, doc_id: str, field_name: str):
    self._TryUpdateUserRequestDocRef(doc_id, {field_name: datetime.now()})

  def _GetUserRequestDocRef(
      self, doc_id: Optional[str] = None) -> firestore.DocumentReference:
    # If doc_id is None, it returns a new document reference with a random 20
    # character string.
    return self._user_request_col_ref.document(doc_id)

  def _TryUpdateUserRequestDocRef(self, doc_id: str, data: Dict[str, Any]):
    try:
      # TODO(b/190484469): Ensure the updating operation will be done
      #     successfully.
      self._GetUserRequestDocRef(doc_id).update(data)
    except Exception as e:
      self._logger.error(e)
