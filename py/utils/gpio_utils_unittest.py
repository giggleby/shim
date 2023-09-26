#!/usr/bin/env python3
# Copyright 2023 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

import abc
import io
import select
import socket
import time
import unittest
from unittest import mock

from cros.factory.utils import gpio_utils
from cros.factory.utils import net_utils


PORT = 1234
TIMEOUT = 0.001  # Set to a small number to make test run faster.
GPIO_VALUE = 1


class _GpioProxy(abc.ABC, net_utils.TimeoutXMLRPCServerProxy):

  @abc.abstractmethod
  def poll_gpio(self, port, edge):
    pass

  @abc.abstractmethod
  def write_gpio(self, port, value):
    pass

  @abc.abstractmethod
  def read_gpio(self, port):
    pass


class GpioManagerTest(unittest.TestCase):

  def testPollInvalidEdge(self):
    gpio_manager = gpio_utils.GpioManager(False)
    self.assertRaises(gpio_utils.GpioManagerError, gpio_manager.Poll, PORT,
                      'invalid_edge')

  @mock.patch.object(gpio_utils, 'Gpio', autospec=True)
  def testPollLocal(self, mock_gpio):
    gpio_manager = gpio_utils.GpioManager(False)
    self.assertTrue(gpio_manager.Poll(PORT, 'gpio_rising', TIMEOUT))

    mock_gpio.assert_called_once_with(PORT)
    mock_gpio_instance = mock_gpio.return_value
    mock_gpio_instance.__enter__.assert_called_once()
    mock_gpio_instance.__exit__.assert_called_once()
    mock_gpio_instance.__enter__().Poll.assert_called_with(
        'gpio_rising', TIMEOUT)

  @mock.patch.object(gpio_utils, 'Gpio', autospec=True)
  def testPollValidEdges(self, mock_gpio):
    del mock_gpio  # unused
    gpio_manager = gpio_utils.GpioManager(False)
    self.assertTrue(gpio_manager.Poll(PORT, 'gpio_rising'))
    self.assertTrue(gpio_manager.Poll(PORT, 'gpio_falling'))
    self.assertTrue(gpio_manager.Poll(PORT, 'gpio_both'))

  @mock.patch.object(gpio_utils.net_utils, 'TimeoutXMLRPCServerProxy',
                     spec=_GpioProxy)
  def testPollRemote(self, mock_server):
    gpio_manager = gpio_utils.GpioManager(True, 'host', PORT, TIMEOUT, True)
    self.assertTrue(gpio_manager.Poll(PORT, 'gpio_rising', TIMEOUT))

    mock_server.assert_called_once_with(f'http://host:{PORT}', timeout=TIMEOUT,
                                        verbose=True)
    mock_server.return_value.poll_gpio.assert_called_with(PORT, 'gpio_rising')

  @unittest.skip("Skip until b/302203801 is fixed")
  @mock.patch.object(gpio_utils.net_utils, 'TimeoutXMLRPCServerProxy',
                     spec=_GpioProxy)
  def testPollRemoteTimeout(self, mock_server):

    def FakePoll(*_):
      time.sleep(TIMEOUT + 0.001)

    gpio_manager = gpio_utils.GpioManager(True, 'host', PORT, TIMEOUT)
    mock_server.return_value.poll_gpio.side_effect = FakePoll

    self.assertFalse(gpio_manager.Poll(PORT, 'gpio_rising', TIMEOUT))

  @mock.patch.object(gpio_utils.net_utils, 'TimeoutXMLRPCServerProxy',
                     spec=_GpioProxy)
  def testPollError(self, mock_server):
    gpio_manager = gpio_utils.GpioManager(True, 'host', PORT)
    mock_server.return_value.poll_gpio.side_effect = gpio_utils.GpioError

    self.assertRaisesRegex(
        gpio_utils.GpioManagerError,
        f'Problem to poll GPIO {PORT} gpio_rising: GpioError()',
        gpio_manager.Poll, PORT, 'gpio_rising')

  @mock.patch.object(gpio_utils, 'Gpio', autospec=True)
  def testReadLocal(self, mock_gpio):
    gpio_manager = gpio_utils.GpioManager(False)
    gpio_manager.Read(PORT)

    mock_gpio.assert_called_once_with(PORT)
    mock_gpio.return_value.__enter__.assert_called_once()
    mock_gpio.return_value.__exit__.assert_called_once()
    mock_gpio.return_value.__enter__().Read.assert_called()

  @mock.patch.object(gpio_utils.net_utils, 'TimeoutXMLRPCServerProxy',
                     spec=_GpioProxy)
  def testReadRemote(self, mock_server):
    gpio_manager = gpio_utils.GpioManager(True, 'host', PORT)
    gpio_manager.Read(PORT)

    mock_server.return_value.read_gpio.assert_called_with(PORT)

  @mock.patch.object(gpio_utils.net_utils, 'TimeoutXMLRPCServerProxy',
                     spec=_GpioProxy)
  def testReadError(self, mock_server):
    gpio_manager = gpio_utils.GpioManager(True, 'host', PORT)
    mock_server.return_value.read_gpio.side_effect = gpio_utils.GpioError

    self.assertRaisesRegex(gpio_utils.GpioManagerError,
                           f'Problem to read GPIO {PORT}: GpioError()',
                           gpio_manager.Read, PORT)

  @mock.patch.object(gpio_utils, 'Gpio', autospec=True)
  def testWriteLocal(self, mock_gpio):
    gpio_manager = gpio_utils.GpioManager(False)
    gpio_manager.Write(PORT, 1)

    mock_gpio.assert_called_once_with(PORT)
    mock_gpio.return_value.__enter__.assert_called_once()
    mock_gpio.return_value.__exit__.assert_called_once()
    mock_gpio.return_value.__enter__().Write.assert_called_with(1)

  @mock.patch.object(gpio_utils.net_utils, 'TimeoutXMLRPCServerProxy',
                     spec=_GpioProxy)
  def testWriteRemote(self, mock_server):
    gpio_manager = gpio_utils.GpioManager(True, 'host', PORT)
    gpio_manager.Write(PORT, GPIO_VALUE)

    mock_server.return_value.write_gpio.assert_called_with(PORT, GPIO_VALUE)

  @mock.patch.object(gpio_utils.net_utils, 'TimeoutXMLRPCServerProxy',
                     spec=_GpioProxy)
  def testWriteError(self, mock_server):
    gpio_manager = gpio_utils.GpioManager(True, 'host', PORT)
    mock_server.return_value.write_gpio.side_effect = gpio_utils.GpioError

    self.assertRaisesRegex(gpio_utils.GpioManagerError,
                           f'Problem to write GPIO {PORT}: GpioError()',
                           gpio_manager.Write, PORT, GPIO_VALUE)


class GpioTest(unittest.TestCase):

  def setUp(self):
    mock_socket = mock.patch.object(gpio_utils.socket, 'socketpair',
                                    autospec=True)
    self.stop_sockets = (
        mock.create_autospec(socket.socket, instance=True),
        mock.create_autospec(socket.socket, instance=True),
    )
    mock_socket.start().return_value = self.stop_sockets
    self.addCleanup(mock.patch.stopall)

  @mock.patch.object(gpio_utils.file_utils, 'WriteFile', autospec=True)
  @mock.patch.object(gpio_utils.os.path, 'exists', autospec=True)
  def testEnter(self, mock_path_exist, mock_write_file):
    mock_path_exist.return_value = True
    with gpio_utils.Gpio(PORT):
      mock_write_file.assert_not_called()
      mock_path_exist.assert_called_with(f'/sys/class/gpio/gpio{PORT}')

    mock_path_exist.return_value = False
    with gpio_utils.Gpio(PORT):
      mock_write_file.assert_called_with('/sys/class/gpio/export', str(PORT))
      mock_path_exist.assert_called_with(f'/sys/class/gpio/gpio{PORT}')

  @mock.patch.object(gpio_utils.file_utils, 'WriteFile', autospec=True)
  def testExit(self, mock_write_file):
    gpio_utils.Gpio(PORT).__exit__(None, None, None)
    mock_write_file.assert_called_with('/sys/class/gpio/unexport', str(PORT))

  @mock.patch.object(gpio_utils.file_utils, 'ReadFile', autospec=True)
  def testRead(self, mock_read_file):
    mock_read_file.return_value = '  0  '

    self.assertEqual(gpio_utils.Gpio(PORT).Read(), 0)
    mock_read_file.assert_called_with(f'/sys/class/gpio/gpio{PORT}/value')

  @mock.patch.object(gpio_utils.file_utils, 'ReadFile', autospec=True)
  def testReadError(self, mock_read_file):
    mock_read_file.side_effect = Exception
    gpio = gpio_utils.Gpio(PORT)
    self.assertRaisesRegex(gpio_utils.GpioError, f'Fail to read GPIO {PORT}',
                           gpio.Read)

  @mock.patch.object(gpio_utils.file_utils, 'WriteFile', autospec=True)
  def testWrite(self, mock_write_file):
    gpio_utils.Gpio(PORT).Write(GPIO_VALUE)

    mock_write_file.assert_has_calls([
        mock.call(f'/sys/class/gpio/gpio{PORT}/direction', 'out'),
        mock.call(f'/sys/class/gpio/gpio{PORT}/value', str(GPIO_VALUE))
    ])

  @mock.patch.object(gpio_utils.file_utils, 'WriteFile', autospec=True)
  def testWriteError(self, mock_write_file):
    mock_write_file.side_effect = Exception
    gpio = gpio_utils.Gpio(PORT)
    self.assertRaisesRegex(gpio_utils.GpioError,
                           f'Fail to write {GPIO_VALUE} to GPIO {PORT}',
                           gpio.Write, GPIO_VALUE)

  @mock.patch.object(gpio_utils.file_utils, 'WriteFile', autospec=True)
  @mock.patch.object(gpio_utils.select, 'poll', autospec=True)
  def testPoll(self, mock_poll, mock_write_file):
    mock_fd = mock.Mock(io.TextIOWrapper)

    gpio = gpio_utils.Gpio(PORT, mock_fd)
    gpio.Poll('gpio_rising', TIMEOUT)

    mock_write_file.assert_called_with(f'/sys/class/gpio/gpio{PORT}/edge',
                                       'rising')
    mock_poll.return_value.poll.assert_called_with(TIMEOUT * 1000)
    mock_poll.return_value.register.assert_has_calls([
        mock.call(mock_fd, select.POLLPRI | select.POLLERR),
        mock.call(self.stop_sockets[1], select.POLLIN | select.POLLERR)
    ])


if __name__ == '__main__':
  unittest.main()
