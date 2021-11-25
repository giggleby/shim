# Copyright 2021 The Chromium OS Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

import tempfile

from cros.factory.hwid.service.appengine.data import decoder_data
from cros.factory.hwid.service.appengine.data import hwid_db_data
from cros.factory.hwid.service.appengine import hwid_action_manager
from cros.factory.hwid.service.appengine import hwid_preproc_data
from cros.factory.hwid.service.appengine import ndb_connector as ndbc_module
from cros.factory.hwid.v3 import filesystem_adapter


class FakeMemcacheAdapter:

  def __init__(self):
    self._data = {}

  def ClearAll(self):
    self._data.clear()

  def Put(self, key, value):
    self._data[key] = value

  def Get(self, key):
    return self._data.get(key)


class FakeHWIDPreprocData(hwid_preproc_data.HWIDPreprocData):
  CACHE_VERSION = '1'

  def __init__(self, project, raw_db):
    super().__init__(project)
    self.raw_db = raw_db


class FakeHWIDInstanceFactory(hwid_action_manager.InstanceFactory):

  def __init__(self):
    self._hwid_actions = {}

  def CreateHWIDAction(self, hwid_data):
    if not isinstance(hwid_data, FakeHWIDPreprocData):
      raise hwid_action_manager.ProjectUnavailableError()
    registered_hwid_action = self._hwid_actions.get(hwid_data.project)
    if registered_hwid_action is None:
      raise hwid_action_manager.ProjectUnavailableError()
    return registered_hwid_action

  def CreateHWIDPreprocData(self, metadata, raw_db):
    return FakeHWIDPreprocData(metadata.project, raw_db)

  def SetHWIDActionForProject(self, project, hwid_action):
    self._hwid_actions[project] = hwid_action


class FakeModuleCollection:

  def __init__(self):
    self._ndb_connector = ndbc_module.NDBConnector()
    self._tmpdir_for_hwid_db_data = tempfile.TemporaryDirectory()
    self._tempfs_for_hwid_db_data = filesystem_adapter.LocalFileSystemAdapter(
        self._tmpdir_for_hwid_db_data.name)
    self._fake_memcache_for_hwid_preproc_data = FakeMemcacheAdapter()
    self._fake_hwid_instance_factory = FakeHWIDInstanceFactory()

    self.fake_decoder_data_manager = decoder_data.DecoderDataManager(
        self._ndb_connector)
    self.fake_hwid_db_data_manager = hwid_db_data.HWIDDBDataManager(
        self._ndb_connector, self._tempfs_for_hwid_db_data)
    self.fake_goldeneye_memcache = FakeMemcacheAdapter()
    self.fake_hwid_action_manager = hwid_action_manager.HWIDActionManager(
        self.fake_hwid_db_data_manager,
        self._fake_memcache_for_hwid_preproc_data,
        instance_factory=self._fake_hwid_instance_factory)

  def ClearAll(self):
    self.fake_decoder_data_manager.CleanAllForTest()
    self.fake_hwid_db_data_manager.CleanAllForTest()
    self._tmpdir_for_hwid_db_data.cleanup()

  def ConfigHWID(self, project, version, raw_db, hwid_action=None):
    """Specifies the behavior of the fake modules.

    Args:
      project: The project to configure.
      version: Specify the HWID version of the specific project.
      raw_db: Specify the HWID DB contents.
      hwid_action: Specify the corresponding HWIDAction instance.  `None` to
          make the project unavailable.
    """
    self.fake_hwid_db_data_manager.RegisterProjectForTest(
        project, project, str(version), raw_db)
    self._fake_hwid_instance_factory.SetHWIDActionForProject(
        project, hwid_action)
