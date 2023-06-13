# Copyright 2022 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

import datetime
import unittest
from unittest import mock

from google.api_core.datetime_helpers import DatetimeWithNanoseconds
from google.cloud import firestore
import pytz


# isort: split

from cros.factory.bundle_creator.connector import firestore_connector
from cros.factory.bundle_creator.proto import factorybundle_pb2  # pylint: disable=no-name-in-module
from cros.factory.bundle_creator.proto import factorybundle_v2_pb2  # pylint: disable=no-name-in-module


CreateBundleRequestInfo = firestore_connector.CreateBundleRequestInfo


class CreateBundleRequestInfoTest(unittest.TestCase):

  def setUp(self):
    self._request = factorybundle_pb2.CreateBundleRpcRequest()
    self._request.board = 'board'
    self._request.project = 'project'
    self._request.phase = 'proto'
    self._request.toolkit_version = '11111.0.0'
    self._request.test_image_version = '22222.0.0'
    self._request.release_image_version = '33333.0.0'
    self._request.email = 'foo@bar'
    self._request.update_hwid_db_firmware_info = False
    self._request.cc_emails.append('foo.cc@bar')

    self._request_v2 = factorybundle_v2_pb2.CreateBundleRequest()
    self._request_v2.email = 'foo2@bar'
    self._request_v2.bundle_metadata.board = 'board2'
    self._request_v2.bundle_metadata.project = 'project2'
    self._request_v2.bundle_metadata.phase = 'proto2'
    self._request_v2.bundle_metadata.toolkit_version = '55555.0.0'
    self._request_v2.bundle_metadata.test_image_version = '66666.0.0'
    self._request_v2.bundle_metadata.release_image_version = '77777.0.0'
    self._request_v2.hwid_option.update_db_firmware_info = False
    self._request_v2.cc_emails.append('foo2.cc@bar')

  def testFromCreateBundleRpcRequest_succeed_returnsExpectedValue(self):
    info = CreateBundleRequestInfo.FromCreateBundleRpcRequest(self._request)

    expected_info = CreateBundleRequestInfo(
        email='foo@bar', board='board', project='project', phase='proto',
        toolkit_version='11111.0.0', test_image_version='22222.0.0',
        release_image_version='33333.0.0', update_hwid_db_firmware_info=False,
        cc_emails=['foo.cc@bar'])
    self.assertEqual(info, expected_info)

  def testFromCreateBundleRpcRequest_optionalFields_verifiesOptionalFields(
      self):
    self._request.firmware_source = '44444.0.0'
    self._request.hwid_related_bug_number = 1234

    info = CreateBundleRequestInfo.FromCreateBundleRpcRequest(self._request)

    self.assertEqual(info.firmware_source, '44444.0.0')
    self.assertEqual(info.hwid_related_bug_number, 1234)

  def testFromV2CreateBundleRequest_succeed_returnsExpectedValue(self):
    info = CreateBundleRequestInfo.FromV2CreateBundleRequest(self._request_v2)

    expected_info = CreateBundleRequestInfo(
        email='foo2@bar', board='board2', project='project2', phase='proto2',
        toolkit_version='55555.0.0', test_image_version='66666.0.0',
        release_image_version='77777.0.0', update_hwid_db_firmware_info=False,
        cc_emails=['foo2.cc@bar'])
    self.assertEqual(info, expected_info)

  def testFromV2CreateBundleRequest_optionalFields_verifiesOptionalFields(
      self):
    self._request_v2.bundle_metadata.firmware_source = '88888.0.0'
    self._request_v2.hwid_option.related_bug_number = 5678

    info = CreateBundleRequestInfo.FromV2CreateBundleRequest(self._request_v2)

    self.assertEqual(info.firmware_source, '88888.0.0')
    self.assertEqual(info.hwid_related_bug_number, 5678)


class FirestoreConnectorTest(unittest.TestCase):

  _CLOUD_PROJECT_ID = 'fake-project-id'
  _PROJECT = 'project'
  _HAS_FIRMWARE_SETTING_VALUE = ['BIOS']
  _EMPTY_USER_REQUEST_DOC_ID = 'EmptyRequestDocId'
  _FIRESTORE_CURRENT_DATETIME = DatetimeWithNanoseconds(2022, 6, 8, 0, 0,
                                                        tzinfo=pytz.UTC)

  def setUp(self):
    self._info = firestore_connector.CreateBundleRequestInfo(
        email='foo@bar', board='board', project='project', phase='proto',
        toolkit_version='11111.0.0', test_image_version='12222.0.0',
        release_image_version='13333.0.0', update_hwid_db_firmware_info=False,
        cc_emails=[])

    self._datetime_now = datetime.datetime(2022, 6, 8, 0, 0)
    mock_datetime_patcher = mock.patch(
        'cros.factory.bundle_creator.connector.firestore_connector.datetime')
    mock_datetime_patcher.start().now.return_value = self._datetime_now
    self.addCleanup(mock_datetime_patcher.stop)

    self._connector = firestore_connector.FirestoreConnector(
        self._CLOUD_PROJECT_ID)
    self._connector.ClearCollection('has_firmware_settings')
    self._connector.ClearCollection('user_requests')

    client = firestore.Client(project=self._CLOUD_PROJECT_ID)
    self._has_firmware_setting_col = client.collection('has_firmware_settings')
    self._user_requests_col = client.collection('user_requests')
    self._user_requests_col.document(self._EMPTY_USER_REQUEST_DOC_ID).set({})

  def testGetHasFirmwareSettingByProject_succeed_returnsExpectedValues(self):
    self._has_firmware_setting_col.document(self._PROJECT).set(
        {'has_firmware': self._HAS_FIRMWARE_SETTING_VALUE})

    has_firmware_setting = (
        self._connector.GetHasFirmwareSettingByProject(self._PROJECT))

    self.assertEqual(has_firmware_setting, self._HAS_FIRMWARE_SETTING_VALUE)

  def testGetHasFirmwareSettingByProject_keyError_returnsNone(self):
    self._has_firmware_setting_col.document(self._PROJECT).set({})

    has_firmware_setting = (
        self._connector.GetHasFirmwareSettingByProject(self._PROJECT))

    self.assertIsNone(has_firmware_setting)

  def testGetHasFirmwareSettingByProject_documentNotExists_returnsNone(self):
    has_firmware_setting = (
        self._connector.GetHasFirmwareSettingByProject(self._PROJECT))

    self.assertIsNone(has_firmware_setting)

  def testCreateUserRequest_succeed_verifiesCreatedDocument(self):
    doc_id = self._connector.CreateUserRequest(self._info)

    expected_doc = {
        'id': doc_id,
        'email': self._info.email,
        'board': self._info.board,
        'project': self._info.project,
        'phase': self._info.phase,
        'toolkit_version': self._info.toolkit_version,
        'test_image_version': self._info.test_image_version,
        'release_image_version': self._info.release_image_version,
        'status': firestore_connector.UserRequestStatus.NOT_STARTED.name,
        'request_time': self._FIRESTORE_CURRENT_DATETIME,
        'update_hwid_db_firmware_info': False,
    }
    doc = self._connector.GetUserRequestDocument(doc_id)
    self.assertEqual(doc, expected_doc)

  def testCreateUserRequest_hasFirmwareSource_verifiesFirmwareSourceValue(self):
    self._info.firmware_source = '14444.0.0'

    doc_id = self._connector.CreateUserRequest(self._info)

    doc = self._connector.GetUserRequestDocument(doc_id)
    self.assertEqual(doc['firmware_source'], self._info.firmware_source)

  def testCreateUserRequest_updateHWIDFirmwareInfo_verifiesRelatedValues(self):
    self._info.update_hwid_db_firmware_info = True
    self._info.hwid_related_bug_number = 123456789

    doc_id = self._connector.CreateUserRequest(self._info)

    doc = self._connector.GetUserRequestDocument(doc_id)
    self.assertEqual(doc['update_hwid_db_firmware_info'], True)
    self.assertEqual(doc['hwid_related_bug_number'],
                     self._info.hwid_related_bug_number)

  def testCreateUserRequest_callWithRequestFrom_verifiesRequestFromValue(self):
    request_from = 'v2'

    doc_id = self._connector.CreateUserRequest(self._info, request_from)

    doc = self._connector.GetUserRequestDocument(doc_id)
    self.assertEqual(doc['request_from'], request_from)

  def testCreateUserRequest_hasCcEmails_verifiesCcEmailsValue(self):
    self._info.cc_emails.append('foo.cc@bar')

    doc_id = self._connector.CreateUserRequest(self._info)

    doc = self._connector.GetUserRequestDocument(doc_id)
    self.assertEqual(doc['cc_emails'], self._info.cc_emails)

  def testUpdateUserRequestStatus_succeed_verifiesDocStatus(self):
    status = firestore_connector.UserRequestStatus.SUCCEEDED

    self._connector.UpdateUserRequestStatus(self._EMPTY_USER_REQUEST_DOC_ID,
                                            status)

    doc = self._connector.GetUserRequestDocument(
        self._EMPTY_USER_REQUEST_DOC_ID)
    self.assertEqual(doc['status'], status.name)

  def testUpdateUserRequestStartTime_succeed_verifiesDocStartTime(self):
    self._connector.UpdateUserRequestStartTime(self._EMPTY_USER_REQUEST_DOC_ID)

    doc = self._connector.GetUserRequestDocument(
        self._EMPTY_USER_REQUEST_DOC_ID)
    self.assertEqual(doc['start_time'], self._FIRESTORE_CURRENT_DATETIME)

  def testUpdateUserRequestEndTime_succeed_verifiesDocEndTime(self):
    self._connector.UpdateUserRequestEndTime(self._EMPTY_USER_REQUEST_DOC_ID)

    doc = self._connector.GetUserRequestDocument(
        self._EMPTY_USER_REQUEST_DOC_ID)
    self.assertEqual(doc['end_time'], self._FIRESTORE_CURRENT_DATETIME)

  def testUpdateUserRequestErrorMessage_succeed_verifiesErrorMessage(self):
    error_msg = 'fake_error_message'

    self._connector.UpdateUserRequestErrorMessage(
        self._EMPTY_USER_REQUEST_DOC_ID, error_msg)

    doc = self._connector.GetUserRequestDocument(
        self._EMPTY_USER_REQUEST_DOC_ID)
    self.assertEqual(doc['error_message'], error_msg)

  def testUpdateUserRequestGsPath_succeed_verifiesGsPath(self):
    gs_path = 'gs://fake_path'

    self._connector.UpdateUserRequestGsPath(self._EMPTY_USER_REQUEST_DOC_ID,
                                            gs_path)

    doc = self._connector.GetUserRequestDocument(
        self._EMPTY_USER_REQUEST_DOC_ID)
    self.assertEqual(doc['gs_path'], gs_path)

  def testGetUserRequestsByEmail_succeed_returnsExpectedDocuments(self):
    email = 'foo@bar'
    self._user_requests_col.document('doc_1').set({
        'email': email,
        'request_time': datetime.datetime(2022, 5, 20, 0, 0),
    })
    self._user_requests_col.document('doc_2').set({
        'email': email,
        'request_time': datetime.datetime(2022, 5, 21, 0, 0),
    })
    self._user_requests_col.document('doc_3').set({
        'email': 'foo2@bar',
        'request_time': datetime.datetime(2022, 5, 22, 0, 0),
    })

    user_requests = self._connector.GetUserRequestsByEmail(email)

    self.assertEqual(user_requests, [{
        'id':
            'doc_2',
        'email':
            email,
        'request_time':
            DatetimeWithNanoseconds(2022, 5, 21, 0, 0, tzinfo=pytz.UTC),
    }, {
        'id':
            'doc_1',
        'email':
            email,
        'request_time':
            DatetimeWithNanoseconds(2022, 5, 20, 0, 0, tzinfo=pytz.UTC),
    }])

  def testGetUserRequestsByProject_succeed_returnsExpectedDocuments(self):
    project = 'project'
    self._user_requests_col.document('doc_1').set({
        'email': 'foo@bar',
        'project': project,
        'request_time': datetime.datetime(2022, 12, 24, 0, 0),
    })
    self._user_requests_col.document('doc_2').set({
        'email': 'foo2@bar',
        'project': 'other_project',
        'request_time': datetime.datetime(2022, 12, 25, 0, 0),
    })
    self._user_requests_col.document('doc_3').set({
        'email': 'foo3@bar',
        'project': project,
        'request_time': datetime.datetime(2022, 12, 26, 0, 0),
    })

    user_requests = self._connector.GetUserRequestsByProject(project)

    self.assertEqual(user_requests, [{
        'id':
            'doc_3',
        'email':
            'foo3@bar',
        'project':
            project,
        'request_time':
            DatetimeWithNanoseconds(2022, 12, 26, 0, 0, tzinfo=pytz.UTC),
    }, {
        'id':
            'doc_1',
        'email':
            'foo@bar',
        'project':
            project,
        'request_time':
            DatetimeWithNanoseconds(2022, 12, 24, 0, 0, tzinfo=pytz.UTC),
    }])

  def testGetLatestUserRequestsByStatus_succeed_returnsExpectedDocuments(self):
    status = firestore_connector.UserRequestStatus.FAILED
    self._user_requests_col.document('doc_1').set({
        'status': status.name,
        'request_time': self._datetime_now - datetime.timedelta(days=1000),
    })
    self._user_requests_col.document('doc_2').set({
        'status': status.name,
        'request_time': self._datetime_now,
    })
    self._user_requests_col.document('doc_3').set({
        'status': firestore_connector.UserRequestStatus.SUCCEEDED.name,
        'request_time': self._datetime_now,
    })
    self._user_requests_col.document('doc_4').set({
        'status': firestore_connector.UserRequestStatus.NOT_STARTED.name,
        'request_time': self._datetime_now,
    })

    user_requests = self._connector.GetLatestUserRequestsByStatus(status)

    self.assertEqual(user_requests, [{
        'id':
            'doc_2',
        'status':
            status.name,
        'request_time':
            DatetimeWithNanoseconds(2022, 6, 8, 0, 0, tzinfo=pytz.UTC),
    }, {
        'id':
            'doc_1',
        'status':
            status.name,
        'request_time':
            DatetimeWithNanoseconds(2019, 9, 12, 0, 0, tzinfo=pytz.UTC),
    }])

  def testGetLatestUserRequestsByStatus_hasWithinDays_returnsExpectedDocuments(
      self):
    status = firestore_connector.UserRequestStatus.FAILED
    self._user_requests_col.document('doc_1').set({
        'status': status.name,
        'request_time': self._datetime_now - datetime.timedelta(days=7),
    })
    self._user_requests_col.document('doc_2').set({
        'status': status.name,
        'request_time': self._datetime_now - datetime.timedelta(days=11),
    })

    user_requests = self._connector.GetLatestUserRequestsByStatus(status, 10)

    self.assertEqual(user_requests, [{
        'id':
            'doc_1',
        'status':
            status.name,
        'request_time':
            DatetimeWithNanoseconds(2022, 6, 1, 0, 0, tzinfo=pytz.UTC),
    }])

  def testUpdateHWIDCLURLAndErrorMessage_onlyCLURL_verifiesDocument(self):
    cl_url = ['https://fake_cl_url']

    self._connector.UpdateHWIDCLURLAndErrorMessage(
        self._EMPTY_USER_REQUEST_DOC_ID, cl_url, None)

    doc = self._connector.GetUserRequestDocument(
        self._EMPTY_USER_REQUEST_DOC_ID)
    self.assertEqual(doc['hwid_cl_url'], cl_url)
    self.assertNotIn('hwid_cl_error_msg', doc)

  def testUpdateHWIDCLURLAndErrorMessage_onlyCLErrorMsg_verifiesDocument(self):
    cl_error_msg = '{"fake_error": "fake_message"}'

    self._connector.UpdateHWIDCLURLAndErrorMessage(
        self._EMPTY_USER_REQUEST_DOC_ID, [], cl_error_msg)

    doc = self._connector.GetUserRequestDocument(
        self._EMPTY_USER_REQUEST_DOC_ID)
    self.assertNotIn('hwid_cl_url', doc)
    self.assertEqual(doc['hwid_cl_error_msg'], cl_error_msg)

  def testUpdateHWIDCLURLAndErrorMessage_bothEmpty_verifiesDocument(self):
    self._connector.UpdateHWIDCLURLAndErrorMessage(
        self._EMPTY_USER_REQUEST_DOC_ID, [], None)

    doc = self._connector.GetUserRequestDocument(
        self._EMPTY_USER_REQUEST_DOC_ID)
    self.assertNotIn('hwid_cl_url', doc)
    self.assertNotIn('hwid_cl_error_msg', doc)


if __name__ == '__main__':
  unittest.main()
