# Copyright (c) 2014 The Chromium OS Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""System helper functions.

Umpire is designed to run on Linux with Upstart event-based init daemon. This
module provides helper functions to install Umpire conf file, register Umpire
user and group.
"""

import dbus
import errno
import grp
import logging
import os
import pwd
import shutil
import subprocess

import factory_common  # pylint: disable=W0611
from cros.factory.umpire import common
from cros.factory.utils import file_utils, process_utils


# Umpire init creates a group with same name as user.
UMPIRE_USER_GROUP = 'umpire'
UMPIRE_UPSTART = 'umpire'

# Umpire Upstart configuration
_UPSTART_CONF_DST = '/etc/init/umpire.conf'
_UPSTART_CONF_SRC = os.path.join(os.path.basedir(__file__), 'umpire.conf')


def NeedRootPermission(func):
  """Decorates the function to log error message on EPERM."""
  def Wrapped(*args, **kwargs):
    try:
      return func(*args, **kwargs)
    except IOError as e:
      if e[0] == errno.EPERM:
        logging.error('%s: you will need root permission to call',
                      func.__name__)
      raise
  return Wrapped


class Upstart(object):
  """Simple Upstart control.

  Properties:
    bus: DBus system bus.
    manager_object: Upstart manager object.
    job_object: Specified job objet.
    instance_object: Job instance.
    instance_properties: Properties dict.
  """
  BUS_NAME = 'com.ubuntu.Upstart'
  OBJECT_PATH = '/com/ubuntu/upstart'
  INTERFACE = 'com.ubuntu.Upstart0_6'
  INTERFACE_JOB = INTERFACE + '.Job'
  INTERFACE_INSTANCE = INTERFACE + '.Instance'

  def __init__(self, conf_name):
    """Constructs Upstart configuration controller.

    Args:
      conf_name: Upstart configuration name.

    Raises:
      common.UmpireError: when failed to create Upstart job proxy.
    """
    super(Upstart, self).__init__()
    self.job_object = None
    self.instance_object = None
    self.instance_properties = {}
    # Get Upstart manager object.
    self.bus = dbus.SystemBus()
    self.manager_object = self.bus.get_object(self.BUS_NAME, self.OBJECT_PATH)
    if not self.manager_object:
      raise common.UmpireError('Can not get upstart manager proxy.')
    # And get job object, instance object and instance properties dict.
    if not self._GetJobObject(conf_name):
      logging.error('Can not get Upstart job object: %s', conf_name)
      raise common.UmpireError('Can not get %s upstart object' % conf_name)

    self._GetInstanceObject()
    self._FetchInstanceProperties()

  def _GetJobObject(self, conf_name):
    """Gets job proxy.

    _GetJobObject() calls manager proxy's GetJobByName() to lookup specified
    configuration name. Once the return job path is valid, it fetches job
    proxy from the bus.

    Args:
      conf_name: the upstart configuration name in /etc/init.

    Returns:
      Job proxy when conf_name found, otherwise None.
    """
    job_path = self.manager_object.GetJobByName(
        conf_name, dbus_interface=self.INTERFACE)
    if job_path:
      logging.debug('Got Upstart job "%s" path: %s', conf_name, job_path)
      self.job_object = self.bus.get_object(self.BUS_NAME, job_path)
    else:
      self.job_object = None
    return self.job_object

  def _GetInstanceObject(self, instance_path=None):
    """Gets instance proxy.

    Python DBus object is an RPC proxy. _GetInstanceObject() calls
    job_proxy.GetInstance() to fetch instance path. And creates
    instance proxy from bus.

    Args:
      instance_path: if instance path is specified, this function skips
                     the path lookup step.

    Returns:
      None if one of job proxy or instance path is not available, otherwise
      instance proxy object.
    """
    if not self.job_object:
      self.instance_object = None
      return None
    if not instance_path:
      instance_path = self.job_object.GetInstance(
          [], dbus_interface=self.INTERFACE_JOB)
    if instance_path:
      logging.debug('Got instance path: %s', instance_path)
      self.instance_object = self.bus.get_object(self.BUS_NAME, instance_path)
    else:
      self.instance_object = None
    return self.instance_object

  def _FetchInstanceProperties(self):
    """Retrieves instance properties."""
    if self.instance_object:
      self.instance_properties = self.instance_object.GetAll(
          self.INTERFACE_INSTANCE, dbus_interface=dbus.PROPERTIES_IFACE)
      logging.debug('instance properties: %r', self.instance_properties)
    else:
      self.instance_properties = {}
    return self.instance_properties

  @NeedRootPermission
  def Start(self, env=None, wait=True):
    """Starts the Upstart configuration and updates instance properties."""
    if not env:
      env = []
    instance_path = self.job_object.Start(env, wait)
    self._GetInstanceObject(instance_path)
    self._FetchInstanceProperties()

  @NeedRootPermission
  def Stop(self, env=None, wait=True):
    """Stops the Upstart configuration."""
    if not env:
      env = []
    self.job_object.Stop(env, wait)
    self._GetInstanceObject()
    self._FetchInstanceProperties()

  @NeedRootPermission
  def Restart(self, env=None, wait=True):
    """Restarts the Upstart configuration."""
    if not env:
      env = []
    instance_path = self.job_object.Restart(env, wait)
    self._GetInstanceObject(instance_path)
    self._FetchInstanceProperties()


@NeedRootPermission
def CreateUmpireUser():
  """Creates Umpire user and group.

  If Umpire user and group already exist, return its (uid, gid) tuple.

  Returns:
    (uid, gid): A tuple contains user id and group id.

  Raises:
    subprocess.CalledProcessError: when called with wrong input args.
    IOError(EPERM): need permissions.
    KeyError: can not fetch Umpire user/group from system.
  """
  with file_utils.TempDirectory() as temp_dir:
    args = [
        'useradd',
        '--system',                 # Umpire is a system account.
        '--user-group',             # Create a group with same name as user.
        '--shell', '/bin/nologin',  # Umpire will not login.
        '--home', '/var/db/factory/umpire',
        '--create-home',
        '--skel', temp_dir,         # Create empty home.
        '--comment', 'Umpire',
        UMPIRE_USER_GROUP]
    process = process_utils.Spawn(args, read_stdout=True, read_stderr=True)
    unused_stdout, stderr = process.communicate()
    # Ignore useradd return codes:
    #   9 : username already in use
    #   12: can not create home
    if process.returncode not in [0, 9, 12]:
      # Raise on permission errors:
      #   1: can not update passwd
      #   10: can not update group
      #   13: can not create spool
      if process.returncode in [1, 10, 13]:
        raise IOError(errno.EPERM, stderr)
      raise subprocess.CalledProcessError(process.returncode, args)

  umpire_user = pwd.getpwnam(UMPIRE_USER_GROUP)
  umpire_group = grp.getgrnam(UMPIRE_USER_GROUP)
  return (umpire_user.pw_uid, umpire_group.pw_gid)


@NeedRootPermission
def CreateUmpireUpstart():
  """Creates Umpire Upstart script."""
  shutil.copy(_UPSTART_CONF_SRC, _UPSTART_CONF_DST)


@NeedRootPermission
def StartUmpire(board):
  """Starts Umpire Upstart script.

  Args:
    board: DUT board name.
  """
  umpire_controller = Upstart(UMPIRE_UPSTART)
  umpire_controller.Start(env=['BOARD=%s' % board])
  logging.debug('Umpire Upstart configuration started: %r',
                umpire_controller.instance_properties)


@NeedRootPermission
def RestartUmpire(board):
  """Restarts Umpire Upstart script.

  Args:
    board: DUT board name.
  """
  umpire_controller = Upstart(UMPIRE_UPSTART)
  umpire_controller.Restart(env=['BOARD=%s' % board])
  logging.debug('Umpire Upstart configuration restarted: %r',
                umpire_controller.instance_properties)
