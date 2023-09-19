#!/usr/bin/env python3
# Copyright 2023 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.
"""Tests for cros.hwid.service.appengine.hwid_api"""

import unittest
from unittest import mock

from cros.factory.hwid.service.appengine import hwid_action
from cros.factory.hwid.service.appengine.hwid_api_helpers import bom_and_configless_helper as bc_helper_module
from cros.factory.hwid.service.appengine.hwid_api_helpers import project_info_apis
from cros.factory.hwid.service.appengine.proto import hwid_api_messages_pb2  # pylint: disable=no-name-in-module
from cros.factory.hwid.service.appengine import test_utils
from cros.factory.hwid.v3 import database


AVLInfoMsg = hwid_api_messages_pb2.AvlInfo
ComponentMsg = hwid_api_messages_pb2.Component
FieldMsg = hwid_api_messages_pb2.Field
StatusMsg = hwid_api_messages_pb2.Status
SupportStatus = hwid_api_messages_pb2.ComponentSupportStatus.Case


class ProtoRPCServiceTest(unittest.TestCase):

  def setUp(self):
    super().setUp()
    self._modules = test_utils.FakeModuleCollection()
    self._bc_helper = mock.Mock(
        spec=bc_helper_module.BOMAndConfiglessHelper,
        wraps=bc_helper_module.BOMAndConfiglessHelper(
            self._modules.fake_decoder_data_manager,
            self._modules.fake_bom_data_cacher))
    self.service = project_info_apis.ProjectInfoShard(
        self._modules.fake_hwid_action_manager,
        self._modules.fake_hwid_db_data_manager, self._bc_helper)

  def tearDown(self):
    super().tearDown()
    self._modules.ClearAll()

  def testGetProjects(self):
    self._modules.ConfigHWID('ALPHA', '2', 'db1')
    self._modules.ConfigHWID('BRAVO', '3', 'db2')
    self._modules.ConfigHWID('CHARLIE', '3', 'db3')

    req = hwid_api_messages_pb2.ProjectsRequest()
    msg = self.service.GetProjects(req)

    self.assertEqual(
        hwid_api_messages_pb2.ProjectsResponse(
            status=StatusMsg.SUCCESS,
            projects=sorted(['ALPHA', 'BRAVO', 'CHARLIE'])), msg)

  def testGetHwids_ProjectNotFound(self):
    # There's no project in the backend datastore by default.

    req = hwid_api_messages_pb2.HwidsRequest(project='no_such_project')
    msg = self.service.GetHwids(req)

    self.assertEqual(msg.status, StatusMsg.NOT_FOUND)

  def testGetHwids_InternalError(self):
    self._modules.ConfigHWID('FOO', '3', 'db data', None)

    req = hwid_api_messages_pb2.HwidsRequest(project='foo')
    msg = self.service.GetHwids(req)

    self.assertEqual(msg.status, StatusMsg.SERVER_ERROR)

  def testGetHwids_BadRequestError(self):
    hwid_action_inst = hwid_action.HWIDAction()
    with mock.patch.object(hwid_action_inst, '_EnumerateHWIDs') as method:
      method.return_value = ['alfa', 'bravo', 'charlie']
      self._modules.ConfigHWID('FOO', '3', 'db data', hwid_action_inst)

      req = hwid_api_messages_pb2.HwidsRequest(project='foo',
                                               with_classes=['foo', 'bar'],
                                               without_classes=['bar', 'baz'])
      msg = self.service.GetHwids(req)

    self.assertEqual(msg.status, StatusMsg.BAD_REQUEST)

  def testGetHwids_Success(self):
    hwid_action_inst = hwid_action.HWIDAction()
    with mock.patch.object(hwid_action_inst, '_EnumerateHWIDs') as method:
      method.return_value = ['alfa', 'bravo', 'charlie']
      self._modules.ConfigHWID('FOO', '3', 'db data', hwid_action_inst)

      req = hwid_api_messages_pb2.HwidsRequest(project='foo')
      msg = self.service.GetHwids(req)

    self.assertEqual(
        hwid_api_messages_pb2.HwidsResponse(
            status=StatusMsg.SUCCESS, hwids=['alfa', 'bravo', 'charlie']), msg)

  def testGetComponentClasses_ProjectNotFoundError(self):
    # There's no project in the backend datastore by default.

    req = hwid_api_messages_pb2.ComponentClassesRequest(project='nosuchproject')
    msg = self.service.GetComponentClasses(req)

    self.assertEqual(msg.status, StatusMsg.NOT_FOUND)

  def testGetComponentClasses_ProjectUnavailableError(self):
    self._modules.ConfigHWID('FOO', '3', 'db data', None)

    req = hwid_api_messages_pb2.ComponentClassesRequest(project='foo')
    msg = self.service.GetComponentClasses(req)

    self.assertEqual(msg.status, StatusMsg.SERVER_ERROR)

  def testGetComponentClasses_Success(self):
    fake_hwid_action = mock.create_autospec(hwid_action.HWIDAction,
                                            instance=True)
    fake_hwid_action.GetComponentClasses.return_value = ['dram', 'storage']
    self._modules.ConfigHWID('FOO', '3', 'db data', fake_hwid_action)

    req = hwid_api_messages_pb2.ComponentClassesRequest(project='foo')
    msg = self.service.GetComponentClasses(req)

    self.assertEqual(msg.status, StatusMsg.SUCCESS)
    self.assertCountEqual(list(msg.component_classes), ['dram', 'storage'])

  def testGetComponents_ProjectNotFoundError(self):
    # There's no project in the backend datastore by default.

    req = hwid_api_messages_pb2.ComponentsRequest(project='nosuchproject')
    msg = self.service.GetComponents(req)

    self.assertEqual(msg.status, StatusMsg.NOT_FOUND)

  def testGetComponents_ProjectUnavailableError(self):
    self._modules.ConfigHWID('FOO', '3', 'db data', None)

    req = hwid_api_messages_pb2.ComponentsRequest(project='foo')
    msg = self.service.GetComponents(req)

    self.assertEqual(msg.status, StatusMsg.SERVER_ERROR)

  def testGetComponents_SuccessWithAllComponentClasses(self):
    sampled_components = {
        'dram': {
            'dram1': database.ComponentInfo({'key': 'value'}, 'supported')
        },
        'storage': {
            'storage1': database.ComponentInfo({'key': 'value'}, 'supported')
        },
    }

    def FakeGetComponents(with_classes=None):
      return {
          k: v
          for k, v in sampled_components.items()
          if with_classes is None or k in with_classes
      }

    fake_hwid_action = mock.create_autospec(hwid_action.HWIDAction,
                                            instance=True)
    fake_hwid_action.GetComponents.side_effect = FakeGetComponents
    self._modules.ConfigHWID('FOO', '3', 'db data', fake_hwid_action)

    req = hwid_api_messages_pb2.ComponentsRequest(project='foo')
    msg = self.service.GetComponents(req)

    self.assertEqual(msg.status, StatusMsg.SUCCESS)
    self.assertCountEqual(
        list(msg.components), [
            ComponentMsg(component_class='dram', name='dram1',
                         status=SupportStatus.SUPPORTED),
            ComponentMsg(component_class='storage', name='storage1',
                         status=SupportStatus.SUPPORTED),
        ])

  def testGetComponents_SuccessWithLimitedComponentClasses(self):
    sampled_components = {
        'dram': {
            'dram1': database.ComponentInfo({'key': 'value'}, 'supported')
        },
        'storage': {
            'storage1': database.ComponentInfo({'key': 'value'}, 'supported')
        },
    }

    def FakeGetComponents(with_classes=None):
      return {
          k: v
          for k, v in sampled_components.items()
          if with_classes is None or k in with_classes
      }

    fake_hwid_action = mock.create_autospec(hwid_action.HWIDAction,
                                            instance=True)
    fake_hwid_action.GetComponents.side_effect = FakeGetComponents
    self._modules.ConfigHWID('FOO', '3', 'db data', fake_hwid_action)

    req = hwid_api_messages_pb2.ComponentsRequest(project='foo',
                                                  with_classes=['dram'])
    msg = self.service.GetComponents(req)

    self.assertEqual(msg.status, StatusMsg.SUCCESS)
    self.assertCountEqual(
        list(msg.components), [
            ComponentMsg(component_class='dram', name='dram1',
                         status=SupportStatus.SUPPORTED),
        ])

  def testGetComponents_SuccessWithVerbose(self):
    sampled_components = {
        'dram': {
            'dram_1_2': database.ComponentInfo({'key': 'value'}, 'supported')
        },
        'storage': {
            'storage1': database.ComponentInfo({'key': 'value'}, 'supported')
        },
    }

    def FakeGetComponents(with_classes=None):
      return {
          k: v
          for k, v in sampled_components.items()
          if with_classes is None or k in with_classes
      }

    fake_hwid_action = mock.create_autospec(hwid_action.HWIDAction,
                                            instance=True)
    fake_hwid_action.GetComponents.side_effect = FakeGetComponents
    self._modules.ConfigHWID('FOO', '3', 'db data', fake_hwid_action)

    req = hwid_api_messages_pb2.ComponentsRequest(project='foo', verbose=True)
    msg = self.service.GetComponents(req)

    self.assertEqual(msg.status, StatusMsg.SUCCESS)
    self.assertCountEqual(
        list(msg.components), [
            ComponentMsg(component_class='dram', name='dram_1_2', fields=[
                FieldMsg(name='key', value='value')
            ], avl_info=AVLInfoMsg(cid=1, qid=2), has_avl=True,
                         status=SupportStatus.SUPPORTED),
            ComponentMsg(component_class='storage', name='storage1', fields=[
                FieldMsg(name='key', value='value')
            ], status=SupportStatus.SUPPORTED),
        ])


if __name__ == '__main__':
  unittest.main()
