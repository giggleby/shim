# Copyright 2022 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

import io
import json
from typing import List, Tuple
import unittest
from unittest import mock
import urllib.error

from cros.factory.bundle_creator.connector import hwid_api_connector

_TOKEN = 'ZMhb.D.xWPbbBTkiJsPri-KEYyLlLL99zXrnPqotEf1BKgpqmk'


def _MockGoogleAuthDefault(scopes: List[str]) -> Tuple[mock.Mock, None]:
  if 'https://www.googleapis.com/auth/chromeoshwid' in scopes:
    credentials = mock.Mock(token=_TOKEN)
    return (credentials, None)
  raise ValueError('The scopes don\'t contain `chromeoshwid`.')


class HWIDAPIConnectorTest(unittest.TestCase):

  _HWID_ENDPOINT = 'https://fake_hwid_endpoint'
  _ORIGINAL_REQUESTER = 'foo@bar'
  _BUNDLE_RECORD = '{"fake_key": "fake_value"}'
  _BUG_NUMBER = 123456789
  _PHASE = 'PVT'

  def setUp(self):
    mock_urllib_request_patcher = mock.patch('urllib.request')
    self._urllib_request = mock_urllib_request_patcher.start()
    self.addCleanup(mock_urllib_request_patcher.stop)

    mock_google_auth_default_patcher = mock.patch('google.auth.default')
    self._google_auth_default = mock_google_auth_default_patcher.start()
    self.addCleanup(mock_google_auth_default_patcher.stop)
    self._google_auth_default.side_effect = _MockGoogleAuthDefault

    self._connector = hwid_api_connector.HWIDAPIConnector(self._HWID_ENDPOINT)

  def testCreateHWIDFirmwareInfoCL_verifyRequestWithExpectedArguments(self):
    mock_response = mock.Mock()
    mock_response.read.return_value = '{}'
    self._urllib_request.urlopen.return_value.__enter__.return_value = (
        mock_response)

    self._connector.CreateHWIDFirmwareInfoCL(self._BUNDLE_RECORD,
                                             self._ORIGINAL_REQUESTER,
                                             self._BUG_NUMBER, self._PHASE)

    self.assertEqual(
        self._urllib_request.Request.call_args.args[0],
        f'{self._HWID_ENDPOINT}/v2/createHwidDbFirmwareInfoUpdateCl')
    self.assertEqual(
        self._urllib_request.Request.call_args.kwargs['headers']
        ['Authorization'], f'Bearer {_TOKEN}')
    data = json.loads(self._urllib_request.Request.call_args.kwargs['data'])
    self.assertEqual(data['bundle_record'], self._BUNDLE_RECORD)
    self.assertEqual(data['original_requester'], self._ORIGINAL_REQUESTER)
    self.assertEqual(data['bug_number'], self._BUG_NUMBER)
    self.assertEqual(data['phase'], self._PHASE)

  def testCreateHWIDFirmwareInfoCL_succeed_returnsExpectedClUrl(self):
    cl_number = 1234567
    mock_response = mock.Mock()
    mock_response.read.return_value = json.dumps({
        'commits': {
            'project': {
                'clNumber': cl_number,
            },
        },
    })
    self._urllib_request.urlopen.return_value.__enter__.return_value = (
        mock_response)

    cl_url = self._connector.CreateHWIDFirmwareInfoCL(
        self._BUNDLE_RECORD, self._ORIGINAL_REQUESTER, self._BUG_NUMBER,
        self._PHASE)

    expected_url = (
        'https://chrome-internal-review.googlesource.com/c/chromeos/'
        f'chromeos-hwid/+/{cl_number}')
    self.assertEqual(cl_url, [expected_url])

  def testCreateHWIDFirmwareInfoCL_httpError_raisesExpectedException(self):
    error_msg = {
        'error': {
            'code': 403,
        },
    }
    forbidden_error = urllib.error.HTTPError(
        url='', code=403, msg='', hdrs={}, fp=io.StringIO(
            json.dumps(error_msg)))
    self._urllib_request.urlopen.side_effect = forbidden_error

    with self.assertRaises(hwid_api_connector.HWIDAPIRequestException) as e:
      self._connector.CreateHWIDFirmwareInfoCL(self._BUNDLE_RECORD,
                                               self._ORIGINAL_REQUESTER,
                                               self._BUG_NUMBER, self._PHASE)

    self.assertEqual(json.loads(str(e.exception)), error_msg)


if __name__ == '__main__':
  unittest.main()
