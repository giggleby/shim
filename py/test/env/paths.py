#!/usr/bin/env python
# Copyright 2016 The Chromium OS Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

import getpass
import os

import factory_common  # pylint: disable=W0611
from cros.factory.utils import file_utils
from cros.factory.utils import sys_utils


SCRIPT_PATH = os.path.realpath(__file__)
# Path to factory envrionment (code and resources)
FACTORY_PATH = os.path.realpath(os.path.join(SCRIPT_PATH, '..', '..', '..', '..'))
FACTORY_PACKAGE_PATH = os.path.join(FACTORY_PATH, 'py_pkg', 'cros', 'factory')
FACTORY_MD5SUM_PATH = os.path.join(FACTORY_PATH, 'MD5SUM')
FIRMWARE_UPDATER_PATH = os.path.join(
    FACTORY_PATH, 'board', 'chromeos-firmwareupdate')

# Path to stateful partition on device.
DEVICE_STATEFUL_PATH = '/mnt/stateful_partition'

# Name of Chrome data directory within the state directory.
CHROME_DATA_DIR_NAME = 'chrome-data-dir'

# Path to factory log on a "real" device.
FACTORY_LOG_PATH_ON_DEVICE = '/var/factory/log/factory.log'


def get_factory_root(subdir=None):
  """Returns the root for logging and state.

  This is usually /var/log, or /tmp/factory.$USER if in the chroot, but may be
  overridden by the CROS_FACTORY_ROOT environment variable.

  Creates the directory it doesn't exist.

  Args:
   subdir: If not None, returns that subdirectory.
  """
  ret = (os.environ.get('CROS_FACTORY_ROOT') or
         (('/tmp/factory.%s' % getpass.getuser())
          if sys_utils.InChroot() else '/var/factory'))
  if subdir:
    ret = os.path.join(ret, subdir)
  file_utils.TryMakeDirs(ret)
  return ret


def get_log_root():
  """Returns the root for logs"""
  return get_factory_root('log')


def get_state_root():
  """Returns the root for all factory state."""
  return get_factory_root('state')


def get_test_data_root():
  """Returns the root for all test logs/state."""
  return get_factory_root('tests')


def GetConsoleLogPath():
  """Returns the path to console.log file."""
  return os.path.join(get_log_root(), 'console.log')


def GetFactoryLogPath():
  """Returns the path to factory.log file."""
  return os.path.join(get_log_root(), 'factory.log')


def GetFactoryPythonArchivePath():
  """Returns path to a factory python archive.

  This function trys to find a factory python archive.
  If factory toolkit is currently run with a python archive, this function will
  return path to that python archive, otherwise, this function will try to find
  factory.par in default paths.

  If we can't find any, an exception will be raised.
  """

  factory_par = sys_utils.GetRunningFactoryPythonArchivePath()
  if factory_par:
    return factory_par

  factory_par = os.path.join(FACTORY_PATH, 'factory.par')
  if os.path.exists(factory_par):
    return factory_par

  factory_par = os.path.join(FACTORY_PATH, 'factory-mini.par')
  if os.path.exists(factory_par):
    return factory_par

  test_image_factory_mini_par = '/usr/local/factory-mini/factory-mini.par'
  if os.path.exists(test_image_factory_mini_par):
    return test_image_factory_mini_par

  raise EnvironmentError('cannot find factory python archive')
