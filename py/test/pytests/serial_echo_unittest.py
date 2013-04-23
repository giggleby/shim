#!/usr/bin/python
#
# Copyright (c) 2013 The Chromium OS Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

import mox
from mox import IgnoreArg
import serial
import unittest

import factory_common # pylint: disable=W0611
from cros.factory.test.args import Args
from cros.factory.test.pytests import serial_echo
from cros.factory.utils import serial_utils


class SerialEchoUnittest(unittest.TestCase):
  _SEND_RECV = (chr(0xE0), chr(0xE1))
  _SERIAL_PARAM = ('/dev/ttyUSB0', 19200, 8, 'N', 1, 3)
  _DEFAULT_DARGS = {'send_recv': _SEND_RECV,
                    'serial_param': _SERIAL_PARAM}


  def setUp(self):
    self._mox = mox.Mox()
    self._test_case = None
    self._test_result = None

  def tearDown(self):
    self._mox.UnsetStubs()
    self._mox.VerifyAll()

  def SetUpTestCase(self, args, test_case_name='testEcho'):
    self._test_case = serial_echo.SerialEchoTest(test_case_name)
    arg_spec = getattr(self._test_case, 'ARGS', None)
    setattr(self._test_case, 'args', Args(*arg_spec).Parse(args))

  def RunTestCase(self):
    self._test_result = self._test_case.defaultTestResult()
    self._test_case.run(self._test_result)

  def HasError(self, expected_error, assert_message):
    self.assertEqual(1, len(self._test_result.errors), assert_message)
    self.assertTrue(self._test_result.errors[0][1].find(expected_error) != -1,
                    assert_message)

  def HasFailure(self, expected_failure, assert_message):
    self.assertEqual(1, len(self._test_result.failures), assert_message)
    self.assertTrue(
        self._test_result.failures[0][1].find(expected_failure) != -1,
        assert_message)

  def testSuccess(self):
    self._mox.StubOutWithMock(serial_utils, 'OpenSerial')
    mock_serial = self._mox.CreateMock(serial.Serial)
    serial_utils.OpenSerial(IgnoreArg()).AndReturn(mock_serial)

    mock_serial.write(self._SEND_RECV[0]).AndReturn(1)
    mock_serial.read(1).AndReturn(self._SEND_RECV[1])
    mock_serial.close()

    self._mox.ReplayAll()

    self.SetUpTestCase(self._DEFAULT_DARGS)
    self.RunTestCase()
    self.assertEqual(0, len(self._test_result.errors))
    self.assertEqual(0, len(self._test_result.failures))

  def testSuccessReadAny(self):
    self._mox.StubOutWithMock(serial_utils, 'OpenSerial')
    mock_serial = self._mox.CreateMock(serial.Serial)
    serial_utils.OpenSerial(IgnoreArg()).AndReturn(mock_serial)

    mock_serial.write(self._SEND_RECV[0]).AndReturn(1)
    mock_serial.read(1).AndReturn('X')  # Returns some char.
    mock_serial.close()

    serial_utils.OpenSerial(IgnoreArg()).AndReturn(mock_serial)

    mock_serial.write(self._SEND_RECV[0]).AndReturn(1)
    mock_serial.read(1).AndReturn('Z')  # Returns some other char.
    mock_serial.close()

    self._mox.ReplayAll()

    # recv is None.
    self.SetUpTestCase({'send_recv': (chr(0xE0), None),
                        'serial_param': self._SERIAL_PARAM})
    self.RunTestCase()
    self.assertEqual(0, len(self._test_result.errors))
    self.assertEqual(0, len(self._test_result.failures))
    self.RunTestCase()
    self.assertEqual(0, len(self._test_result.errors))
    self.assertEqual(0, len(self._test_result.failures))

  def testSendOnly(self):
    self._mox.StubOutWithMock(serial_utils, 'OpenSerial')
    mock_serial = self._mox.CreateMock(serial.Serial)
    serial_utils.OpenSerial(IgnoreArg()).AndReturn(mock_serial)

    mock_serial.write(self._SEND_RECV[0]).AndReturn(1)
    # No serial.read() is called.
    mock_serial.close()

    self._mox.ReplayAll()

    dargs = dict(self._DEFAULT_DARGS)
    dargs['send_only'] = True
    self.SetUpTestCase(dargs)
    self.RunTestCase()
    self.assertEqual(0, len(self._test_result.errors))
    self.assertEqual(0, len(self._test_result.failures))

  def testSendRecvTupleTooLong(self):
    self.SetUpTestCase({'send_recv': ('tuple', 'too', 'long'),
                        'serial_param': self._SERIAL_PARAM})
    self.RunTestCase()
    self.HasError('Invalid dargs send_recv',
                  'Unable to detect invalid send_recv.')

  def testSendRecvTupleTooShort(self):
    self.SetUpTestCase({'send_recv': ('tuple_too_short', ),
                        'serial_param': self._SERIAL_PARAM})
    self.RunTestCase()
    self.HasError('Invalid dargs send_recv',
                  'Unable to detect invalid send_recv.')

  def testSendRecvTupleNotStr(self):
    self.SetUpTestCase({'send_recv': (1, 2),
                        'serial_param': self._SERIAL_PARAM})
    self.RunTestCase()
    self.HasError('Invalid dargs send_recv',
                  'Unable to detect invalid send_recv.')

  def testCustomFailMessage(self):
    self.SetUpTestCase({'send_recv': (1, 2),
                        'serial_param': self._SERIAL_PARAM,
                        'fail_message': 'Custom fail message'})
    self.RunTestCase()
    self.HasError('Custom fail message',
                  'Unable to set custom fail message.')

  def testOpenSerialFailed(self):
    self._mox.StubOutWithMock(serial_utils, 'OpenSerial')
    serial_utils.OpenSerial(IgnoreArg()).AndRaise(
        serial.SerialException('Failed to open serial port'))
    self._mox.ReplayAll()

    self.SetUpTestCase(self._DEFAULT_DARGS)
    self.RunTestCase()
    self.HasError('Failed to open connection',
                  'Unable to handle OpenSerial exception.')

  def testWriteFail(self):
    self._mox.StubOutWithMock(serial_utils, 'OpenSerial')
    mock_serial = self._mox.CreateMock(serial.Serial)
    serial_utils.OpenSerial(IgnoreArg()).AndReturn(mock_serial)

    mock_serial.write(self._SEND_RECV[0]).AndReturn(0)
    mock_serial.close()

    self._mox.ReplayAll()

    self.SetUpTestCase(self._DEFAULT_DARGS)
    self.RunTestCase()
    self.HasFailure('Failed to send command.',
                    'Unable to handle write failure.')

  def testReadFail(self):
    self._mox.StubOutWithMock(serial_utils, 'OpenSerial')
    mock_serial = self._mox.CreateMock(serial.Serial)
    serial_utils.OpenSerial(IgnoreArg()).AndReturn(mock_serial)

    mock_serial.write(self._SEND_RECV[0]).AndReturn(1)
    mock_serial.read(1).AndReturn('0')
    mock_serial.close()

    self._mox.ReplayAll()

    self.SetUpTestCase(self._DEFAULT_DARGS)
    self.RunTestCase()
    self.HasFailure('Response mismatch',
                    'Unable to handle read failure.')

  def testWriteTimeout(self):
    self._mox.StubOutWithMock(serial_utils, 'OpenSerial')
    mock_serial = self._mox.CreateMock(serial.Serial)
    serial_utils.OpenSerial(IgnoreArg()).AndReturn(mock_serial)

    mock_serial.write(self._SEND_RECV[0]).AndRaise(
        serial.SerialTimeoutException)
    mock_serial.close()

    self._mox.ReplayAll()

    self.SetUpTestCase(self._DEFAULT_DARGS)
    self.RunTestCase()
    self.HasFailure('Timeout sending a command.',
                    'Unable to handle write timeout.')

  def testReadTimeout(self):
    self._mox.StubOutWithMock(serial_utils, 'OpenSerial')
    mock_serial = self._mox.CreateMock(serial.Serial)
    serial_utils.OpenSerial(IgnoreArg()).AndReturn(mock_serial)

    mock_serial.write(self._SEND_RECV[0]).AndReturn(1)
    mock_serial.read(1).AndRaise(serial.SerialTimeoutException)
    mock_serial.close()

    self._mox.ReplayAll()

    self.SetUpTestCase(self._DEFAULT_DARGS)
    self.RunTestCase()
    self.HasFailure('Timeout receiving a response.',
                    'Unable to handle read timeout.')


if __name__ == "__main__":
  unittest.main()
