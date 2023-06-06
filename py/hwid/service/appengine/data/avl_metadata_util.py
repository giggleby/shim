# Copyright 2023 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.
"""Holds data models of blocklist of kernel name of audio codec components."""

import abc
import datetime
import logging
from typing import Sequence

from google.cloud import ndb

from cros.factory.hwid.service.appengine.data import config_data
from cros.factory.hwid.service.appengine import ndb_connector as ndbc_module
from cros.factory.hwid.v3 import database


class AVLMetadataError(Exception):
  """Raised while updating / fetching AVLMetadata fails."""


class AudioCodecBlocklist(ndb.Model):
  """The blocklist of kernel names of audio codec components."""
  kernel_name = ndb.StringProperty()
  time_added = ndb.DateTimeProperty()
  removed = ndb.BooleanProperty(indexed=True)
  time_removed = ndb.DateTimeProperty()


class _SkipAVLChecker(abc.ABC):
  """A class checking if a component should be skipped at AVL validation."""

  @abc.abstractmethod
  def ShouldSkip(self, comp_info: database.ComponentInfo) -> bool:
    """Returns whether this component should skip AVL validations.

    Args:
      comp_info: A database.ComponentInfo instance.

    Raises:
      AVLMetadataError when querying to datastore fails.
    """


class _AudioChecker(_SkipAVLChecker):

  def __init__(self, ndb_connector: ndbc_module.NDBConnector):
    self._ndb_connector = ndb_connector

  def ShouldSkip(self, comp_info: database.ComponentInfo) -> bool:
    """See base class."""

    if comp_info.value_is_none:
      return False

    kernel_name = comp_info.values.get('name')
    if kernel_name is None or not isinstance(kernel_name, str):
      return False
    try:
      with self._ndb_connector.CreateClientContextWithGlobalCache():
        return bool(
            AudioCodecBlocklist.query(
                AudioCodecBlocklist.kernel_name == kernel_name,
                AudioCodecBlocklist.removed == False  # pylint: disable=singleton-comparison
            ).get())
    except Exception as e:
      raise AVLMetadataError(
          'Failed to fetch audio codec blocklist from datastore.') from e


class _AlwaysSkipChecker(_SkipAVLChecker):
  """Always skips AVL check."""

  def ShouldSkip(self, comp_info: database.ComponentInfo) -> bool:
    """See base class."""
    return True


class AVLMetadataManager:

  def __init__(self, ndb_connector: ndbc_module.NDBConnector,
               avl_metadata_setting: config_data.AVLMetadataSetting):
    self._ndb_connector = ndb_connector
    self._avl_metadata_setting = avl_metadata_setting
    self._checkers = {
        'audio_codec': _AudioChecker(self._ndb_connector),
        'sku': _AlwaysSkipChecker(),
    }

  @property
  def avl_metadata_setting(self):
    return self._avl_metadata_setting

  def UpdateAudioCodecBlocklist(self, kernel_name_blocklist: Sequence[str]):
    """Updates the blocklist of audio codec kernel names.

    Args:
      kernel_name_blocklist: A sequence of the kernel names as strings which are
        known software nodes.
    Raises:
      AVLMetadataError when updating to datastore fails.
    """
    kernel_names = set(kernel_name_blocklist)

    try:
      with self._ndb_connector.CreateClientContextWithGlobalCache():
        entries_to_update = []
        # Update entries existing in both part.
        for entry in AudioCodecBlocklist.query():
          if entry.kernel_name in kernel_names:
            kernel_names.discard(entry.kernel_name)
            if not entry.removed:
              continue
            entry.removed = False
            entry.time_added = datetime.datetime.now()
          else:
            if entry.removed:
              continue
            entry.removed = True
            entry.time_removed = datetime.datetime.now()

          entries_to_update.append(entry)

        # Add new entries.
        for kernel_name in kernel_names:
          entries_to_update.append(
              AudioCodecBlocklist(kernel_name=kernel_name,
                                  time_added=datetime.datetime.now(),
                                  removed=False))

        ndb.model.put_multi(entries_to_update)
      logging.info('blocklist of audio codec names is updated.')
    except Exception as e:
      raise AVLMetadataError(
          'Failed to update audio codec blocklist to datastore.') from e

  def SkipAVLCheck(self, comp_cls: str,
                   comp_info: database.ComponentInfo) -> bool:
    """Checks if a component could be excluded from AVL checks.

    Args:
      comp_cls: A string of component class.
      comp_info: A database.ComponentInfo instance.
    Raises:
      AVLMetadataError when querying to datastore fails.
    """
    checker = self._checkers.get(comp_cls)
    if not checker:
      return False

    return checker.ShouldSkip(comp_info)

  def CleanAllForTest(self):
    with self._ndb_connector.CreateClientContext():
      for key in AudioCodecBlocklist.query().iter(keys_only=True):
        key.delete()
