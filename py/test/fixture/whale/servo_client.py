# Copyright (c) 2014 The Chromium OS Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Wrapper of servod interface.

The module provides a simple interface for factory tests to access servod.
Servod is usually running remotely on another device to control Whale fixture.

The ServoClient imitates the logic of dut-control in hdctools. Like dut-control,
ServoClient also uses general string-based interface. So we do not need to
maintain duplicated schema config in both factory and hdctools.

Run 'dut-control -i' to check available attributes of ServoClient for a specific
whale board.

Usage example::

  sc = ServoClient('192.168.0.2', 9999)

  # set attribute
  sc.whale_input_rst = 'on'
  sc.whale_input_rst = 'off'

  # get attribute
  button_state = sc.whale_fixture_start_btn

  # reset servo controls to default values
  sc.hwinit()

"""
# TODO(crosbug.com/p/28870): implement interrupt listener


import re
import xmlrpclib

import factory_common  # pylint: disable=W0611
from cros.factory.utils.net_utils import TimeoutXMLRPCServerProxy


class ServoClientError(Exception):
  """Exception for ServoClient by filtering out actual error messages."""
  def __init__(self, text, e):
    """Constructor for ServoClientError Class

    Args:
      text: A string, error message generated by caller of exception handler
      e: An Exception object supplied by the caught exception.

          For xmlrpclib.Fault.faultString, it has the following format:

          <type 'exception type'>:'actual error message'
    """
    if isinstance(e, xmlrpclib.Fault):
      xmlrpc_error = re.sub('^.*>:', '', e.faultString)
      message = '%s :: %s' % (text, xmlrpc_error)
    else:
      message = '%s :: %s' % (text, e)
    # Pass the message to Exception class.
    super(ServoClientError, self).__init__(message)


class ServoClient(object):
  """Class for servod client to interface with servod via XMLRPC.

  You can set/get servo controls by setting/getting the corresponding
  attributes of this class.

  All exceptions happening in ServoClient are raised as ServoClientError.
  """
  def __init__(self, host, port, timeout=10, verbose=False):
    """Constructor.

    Args:
      host: Name or IP address of servo server host.
      port: TCP port on which servod is listening on.
      timeout: Timeout for HTTP connection.
      verbose: Enables verbose messaging across xmlrpclib.ServerProxy.
    """
    remote = 'http://%s:%s' % (host, port)
    # __setattr__ of this class is overriden.
    super(ServoClient, self).__setattr__(
        '_server', TimeoutXMLRPCServerProxy(remote, timeout=timeout,
                                            verbose=verbose, allow_none=True))

  def _GetControl(self, name):
    """Gets the value from servo for control name.

    Args:
      name: String, name of control to get value from.

    Returns:
      Value read from the control.

    Raises:
      ServoClientError: If error occurs when getting value.
    """
    try:
      return self._server.get(name)
    except Exception as e:
      raise ServoClientError("Problem getting '%s'" % name, e)

  def _SetControl(self, name, value):
    """Sets the value from servo for control name.

    Args:
      name: String, name of control to set.
      value: String, value to set control to.

    Raises:
      ServoClientError: If error occurs when setting value.
    """
    try:
      self._server.set(name, value)
    except Exception as e:
      raise ServoClientError("Problem setting '%s' to '%s'" %
                              (name, value), e)

  def __getattr__(self, name):
    """Delegates getter of all unknown attributes to remote servod.

    Raises:
      ServoClientError: If error occurs when getting value.
    """
    # If name is already in self.__dict__, Python will not invoke this method.
    return self._GetControl(name)

  def __setattr__(self, name, value):
    """Delegates setter of all unknown attributes to remote servod.

    Raises:
      ServoClientError: If error occurs when setting value.
    """
    if name in self.__dict__:  # existing attributes
      super(ServoClient, self).__setattr__(name, value)
    else:
      return self._SetControl(name, value)

  def HWInit(self):
    """Re-initializes the controls to its initial values.

    Raises:
      ServoClientError: If error occurs when invoking hwinit() on servod.
    """
    try:
      self._server.hwinit()
    except Exception as e:
      raise ServoClientError("Problem on HWInit", e)
