#!/usr/bin/env python
# Copyright (c) 2012 The Chromium OS Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.


"""This module handles factory test states (status) and shared persistent data.
"""


from __future__ import print_function

import logging
import os
import shutil
import threading

from jsonrpclib import jsonclass

import factory_common  # pylint: disable=unused-import
from cros.factory.test.env import goofy_proxy
from cros.factory.test.env import paths
from cros.factory.test import event
from cros.factory.test import factory
from cros.factory.test.rules import privacy
from cros.factory.utils import file_utils
from cros.factory.utils import shelve_utils
from cros.factory.utils import sync_utils
from cros.factory.utils import type_utils


# TODO(shunhsingou): Remove the following legacy code.
# Support legacy code. Now the port and address information is defined in
# goofy_proxy module instead of here.
DEFAULT_FACTORY_STATE_PORT = goofy_proxy.DEFAULT_GOOFY_PORT
DEFAULT_FACTORY_STATE_ADDRESS = goofy_proxy.DEFAULT_GOOFY_ADDRESS

DEFAULT_FACTORY_STATE_FILE_DIR = paths.DATA_STATE_DIR

POST_SHUTDOWN_TAG = '%s.post_shutdown'

# Key for device data.  This is a dictionary of accumulated data usually from
# shopfloor calls with information about the configuration of the device.
KEY_DEVICE_DATA = 'device'

KEY_SERIAL_NUMBER = 'serial_number'


def clear_state(state_file_dir=DEFAULT_FACTORY_STATE_FILE_DIR):
  """Clears test state (removes the state file path).

  Args:
    state_file_dir: Path to state; uses the default path if None.
  """
  logging.warn('Clearing state file path %s', state_file_dir)
  if os.path.exists(state_file_dir):
    shutil.rmtree(state_file_dir)


# TODO(shunhsingou): move goofy or dut related functions to goofy_rpc so we can
# really separate them.
@type_utils.UnicodeToStringClass
class FactoryState(object):
  """The core implementation for factory state control.

  The major provided features are:
  SHARED DATA
    You can get/set simple data into the states and share between all tests.
    See get_shared_data(name) and set_shared_data(name, value) for more
    information.

  TEST STATUS
    To track the execution status of factory auto tests, you can use
    get_test_state, get_test_states methods, and update_test_state
    methods.

  All arguments may be provided either as strings, or as Unicode strings in
  which case they are converted to strings using UTF-8. All returned values
  are strings (not Unicode).

  This object is thread-safe.

  See help(FactoryState.[methodname]) for more information.
  """

  _TEST_STATE_POSTFIX = '__test_state__'

  def __init__(self, state_file_dir=None):
    """Initializes the state server.

    Parameters:
      state_file_dir:  External file to store the state information.
    """
    state_file_dir = state_file_dir or DEFAULT_FACTORY_STATE_FILE_DIR
    file_utils.TryMakeDirs(state_file_dir)
    self._tests_shelf = shelve_utils.DictShelfView(
        shelve_utils.OpenShelfOrBackup(state_file_dir + '/tests'))
    self._data_shelf = shelve_utils.DictShelfView(
        shelve_utils.OpenShelfOrBackup(state_file_dir + '/data'))
    self._lock = threading.RLock()

    if factory.TestState not in jsonclass.supported_types:
      jsonclass.supported_types.append(factory.TestState)

  @sync_utils.Synchronized
  def close(self):
    """Shuts down the state instance."""
    for shelf in [self._tests_shelf,
                  self._data_shelf]:
      try:
        shelf.Close()
      except:  # pylint: disable=bare-except
        logging.exception('Unable to close shelf')

  def _convert_test_path_to_key(self, path):
    return shelve_utils.DictKey.Join(path, self._TEST_STATE_POSTFIX)

  def _convert_key_to_test_path(self, key):
    test_path, postfix = shelve_utils.DictKey.Split(key)
    assert postfix == self._TEST_STATE_POSTFIX
    return test_path

  @sync_utils.Synchronized
  def update_test_state(self, path, **kw):
    """Updates the state of a test.

    See factory.TestState.update for the allowable keyword arguments.

    Args:
      path: The path to the test (see FactoryTest for a description
          of test paths).
      kw: See factory.TestState.update for allowable arguments (e.g.,
          status and increment_count).

    Returns:
      A tuple containing the new state, and a boolean indicating whether the
      state was just changed.
    """
    key = self._convert_test_path_to_key(path)
    state = self._tests_shelf.GetValue(key, optional=True)
    old_state_repr = repr(state)
    changed = False

    if not state:
      changed = True
      state = factory.TestState()

    changed = changed | state.update(**kw)  # Don't short-circuit

    if changed:
      logging.debug('Updating test state for %s: %s -> %s',
                    path, old_state_repr, state)
      self._tests_shelf.SetValue(key, state)

    return state, changed

  @sync_utils.Synchronized
  def get_test_state(self, path):
    """Returns the state of a test."""
    key = self._convert_test_path_to_key(path)
    return self._tests_shelf.GetValue(key)

  @sync_utils.Synchronized
  def get_test_paths(self):
    """Returns a list of all tests' paths."""
    # GetKeys() only returns keys that are mapped to a value, therefore, all
    # keys returned should end with `self._TEST_STATE_POSTFIX`.
    keys = self._tests_shelf.GetKeys()
    return [self._convert_key_to_test_path(key) for key in keys]

  @sync_utils.Synchronized
  def get_test_states(self):
    """Returns a map of each test's path to its state."""
    return {path: self.get_test_state(path)
            for path in self.get_test_paths()}

  @sync_utils.Synchronized
  def clear_test_state(self):
    """Clears all test state."""
    self._tests_shelf.Clear()

  @sync_utils.Synchronized
  def set_shared_data(self, key, value):
    """Sets shared data item."""
    self._data_shelf.SetValue(key, value)

  @sync_utils.Synchronized
  def get_shared_data(self, key, optional=False):
    """Retrieves a shared data item.

    Args:
      key: The key whose value to retrieve.
      optional: True to return None if not found; False to raise a KeyError.
    """
    return self._data_shelf.GetValue(key, optional)

  @sync_utils.Synchronized
  def has_shared_data(self, key):
    """Returns if a shared data item exists."""
    return self._data_shelf.HasKey(key)

  @sync_utils.Synchronized
  def del_shared_data(self, key, optional=False):
    """Deletes a shared data item.

    Args:
      key: The key whose value to delete.
      optional: False to raise a KeyError if not found.
    """
    self._data_shelf.DeleteKeys([key], optional)

  @sync_utils.Synchronized
  def update_shared_data_dict(self, key, new_data):
    """Updates values a shared data item whose value is a dictionary.

    This is roughly equivalent to

      data = get_shared_data(key) or {}
      data.update(new_data)
      set_shared_data(key, data)
      return data

    except that it is atomic.

    Args:
      key: The key for the data item to update.
      new_data: A dictionary of items to update.

    Returns:
      The updated value.
    """
    self._data_shelf.UpdateValue(key, new_data)
    return self._data_shelf.GetValue(key)

  @sync_utils.Synchronized
  def delete_shared_data_dict_item(self, shared_data_key,
                                   delete_keys, optional):
    """Deletes items from a shared data item whose value is a dict.

    This is roughly equivalent to

      data = get_shared_data(shared_data_key) or {}
      for key in delete_keys:
        try:
          del data[key]
        except KeyError:
          if not optional:
            raise
      set_shared_data(shared_data_key, data)
      return data

    except that it is atomic.

    Args:
      shared_data_key: The key for the data item to update.
      delete_keys: A list of keys to delete from the dict.
      optional: False to raise a KeyError if not found.

    Returns:
      The updated value.
    """
    data = self.get_shared_data(shared_data_key, optional=True) or {}
    for key in delete_keys:
      try:
        del data[key]
      except KeyError:
        if not optional:
          raise
    self.set_shared_data(shared_data_key, data)
    return data

  @sync_utils.Synchronized
  def append_shared_data_list(self, key, new_item):
    """Appends an item to a shared data item whose value is a list.

    This is roughly equivalent to

      data = get_shared_data(key) or []
      data.append(new_item)
      set_shared_data(key, data)
      return data

    except that it is atomic.

    Args:
      key: The key for the data item to append.
      new_item: The item to be appended.

    Returns:
      The updated value.
    """
    data = self.get_shared_data(key, optional=True) or []
    data.append(new_item)
    self.set_shared_data(key, data)
    return data

  #############################################################################
  # The following functions are exposed for data_shelf APIs.
  # In the future, *_shared_data APIs might be deprecated, users shall use
  # `state_proxy.data_shelf.{GetValue, SetValue, GetKeys, ...}`, which use the
  # following functions.
  #############################################################################
  @sync_utils.Synchronized
  def data_shelf_set_value(self, key, value):
    self._data_shelf.SetValue(key, value)

  @sync_utils.Synchronized
  def data_shelf_get_value(self, key, optional=False):
    return self._data_shelf.GetValue(key, optional)

  @sync_utils.Synchronized
  def data_shelf_has_key(self, key):
    return self._data_shelf.HasKey(key)

  @sync_utils.Synchronized
  def data_shelf_delete_keys(self, keys, optional=False):
    self._data_shelf.DeleteKeys(keys, optional)

  @sync_utils.Synchronized
  def data_shelf_get_children(self, key):
    # Make sure we are returning a list
    return list(self._data_shelf.GetChildren(key))


class DataShelfSelector(object):
  NOTSET = object()

  def __init__(self, proxy, key=None):
    """Constructor

    Args:
      :type proxy: FactoryState
      :type key: basestring
    """
    self._proxy = proxy
    self._key = key

  def SetValue(self, key, value):
    self._proxy.data_shelf_set_value(key, value)

  def GetValue(self, key, default=NOTSET):
    if default == self.NOTSET or self._proxy.data_shelf_has_key(key):
      return self._proxy.data_shelf_get_value(key, False)
    else:
      return default

  def Set(self, value):
    if self._key is None:
      raise ValueError('self._key cannot be None')
    self.SetValue(self._key, value)

  def Get(self, default=NOTSET):
    if self._key is None:
      raise ValueError('self._key cannot be None')
    return self.GetValue(self._key, default=default)

  def __getitem__(self, key):
    if self._key:
      key = shelve_utils.DictKey.Join(self._key, key)
      return self.__class__(self._proxy, key)
    else:
      return self.__class__(self._proxy, key)

  def __setitem__(self, key, value):
    if self._key:
      key = shelve_utils.DictKey.Join(self._key, key)
    self.SetValue(key, value)

  def __iter__(self):
    return iter(self._proxy.data_shelf_get_children(self._key or ''))

  def __contains__(self, key):
    return key in self._proxy.data_shelf_get_children(self._key or '')


def get_instance(address=None, port=None):
  """Gets an instance (for client side) to access the state server.

  Args:
    address: Address of the server to be connected.
    port: Port of the server to be connected.

  Returns:
    :rtype: cros.factory.test.state.FactoryState

    An object with all public functions from FactoryState.
    See help(FactoryState) for more information.
  """
  proxy = goofy_proxy.get_rpc_proxy(
      address, port, goofy_proxy.STATE_URL)
  proxy.__dict__['data_shelf'] = DataShelfSelector(proxy)
  return proxy


# ---------------------------------------------------------------------------
# Helper functions for shared data
def get_shared_data(key, default=None):
  if not get_instance().has_shared_data(key):
    return default
  return get_instance().get_shared_data(key)


def set_shared_data(key, value):
  return get_instance().set_shared_data(key, value)


def has_shared_data(key):
  return get_instance().has_shared_data(key)


def del_shared_data(key):
  return get_instance().del_shared_data(key)


# ---------------------------------------------------------------------------
# Helper functions for device data
def GetDeviceData():
  """Returns the accumulated dictionary of device data."""
  return get_shared_data(KEY_DEVICE_DATA, {})


def DeleteDeviceData(delete_keys, post_update_event=True, optional=False):
  """Returns the accumulated dictionary of device data.

  Args:
    delete_keys: A list of keys to be deleted.
    post_update_event: If True, posts an UPDATE_SYSTEM_INFO event to
        update the test list.
    optional: False to raise a KeyError if not found.

  Returns:
    The updated dictionary.
  """
  logging.info('Deleting device data: %s', delete_keys)
  data = get_instance().delete_shared_data_dict_item(
      KEY_DEVICE_DATA, delete_keys, optional)
  if 'serial_number' in delete_keys:
    SetSerialNumber(None)
  logging.info('Updated device data; complete device data is now %s',
               privacy.FilterDict(data))
  if post_update_event:
    with event.EventClient() as event_client:
      event_client.post_event(event.Event(event.Event.Type.UPDATE_SYSTEM_INFO))
  return data


def UpdateDeviceData(new_device_data, post_update_event=True):
  """Returns the accumulated dictionary of device data.

  Args:
    new_device_data: A dict with key/value pairs to update.  Old values
        are overwritten.
    post_update_event: If True, posts an UPDATE_SYSTEM_INFO event to
        update the test list.

  Returns:
    The updated dictionary.
  """
  logging.info('Updating device data: setting %s',
               privacy.FilterDict(new_device_data))
  data = get_instance().update_shared_data_dict(
      KEY_DEVICE_DATA, new_device_data)
  logging.info('Updated device data; complete device data is now %s',
               privacy.FilterDict(data))
  if post_update_event:
    with event.EventClient() as event_client:
      event_client.post_event(event.Event(event.Event.Type.UPDATE_SYSTEM_INFO))
  return data


# ---------------------------------------------------------------------------
# Helper functions for serial numbers
def SetSerialNumber(serial_number):
  UpdateDeviceData({KEY_SERIAL_NUMBER: serial_number})


def GetSerialNumber():
  return GetDeviceData().get(KEY_SERIAL_NUMBER)


class StubFactoryState(FactoryState):
  def __init__(self):  # pylint: disable=super-init-not-called
    self._tests_shelf = shelve_utils.DictShelfView(shelve_utils.InMemoryShelf())
    self._data_shelf = shelve_utils.DictShelfView(shelve_utils.InMemoryShelf())

    self._lock = threading.RLock()
    self.data_shelf = DataShelfSelector(self)
