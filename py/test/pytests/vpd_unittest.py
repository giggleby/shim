#!/usr/bin/python

# Copyright 2014 The Chromium OS Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

import mox
import unittest
import factory_common  # pylint: disable=W0611

from cros.factory.test.factory import FactoryTestFailure
from cros.factory.test.factory_task import FactoryTask
from cros.factory.test.pytests import vpd
from cros.factory.test.ui_templates import OneSection


# User/group codes for testing.
USER_CODE = ('323232323232323232323232323232323232'
             '323232323232323232323232323256850612')
GROUP_CODE = ('333333333333333333333333333333333333'
              '33333333333333333333333333332dbecc73')

class WriteVPDTaskTest(unittest.TestCase):
  def setUp(self):
    self.test_case = vpd.VPDTest()
    self.test_case.vpd = dict(ro={}, rw={})
    self.write_vpd_task = vpd.WriteVPDTask(self.test_case)
    self.mox = mox.Mox()

  def tearDown(self):
    self.mox.VerifyAll()
    self.mox.UnsetStubs()

  def testGoodUserGroupCode(self):
    self.test_case.registration_code_map = dict(user=USER_CODE,
                                                group=GROUP_CODE)
    # Stub out self.test.template.SetState().
    self.test_case.template = self.mox.CreateMock(OneSection)
    self.mox.StubOutWithMock(self.test_case.template, 'SetState')
    self.test_case.template.SetState(mox.IsA(unicode)).AndReturn(0)
    self.test_case.template.SetState(mox.IsA(str), append=True).AndReturn(0)
    # Stub out Spawn(['vpd', '-i', 'RW_VPD', self.FormatVPDParameter()]).
    self.mox.StubOutWithMock(vpd, 'Spawn')
    vpd.Spawn(mox.IsA(list), log=False, check_call=True).AndReturn(0)
    # Stub out self.Pass().
    self.mox.StubOutWithMock(FactoryTask, 'Pass')
    FactoryTask.Pass().AndReturn(0)  # pylint: disable=E1120

    self.mox.ReplayAll()
    self.write_vpd_task.Run()

  def testTheSameUserGroupCodeFailure(self):
    self.test_case.registration_code_map = dict(user=USER_CODE,
                                                group=USER_CODE)
    # Stub out self.test.template.SetState().
    self.test_case.template = self.mox.CreateMock(OneSection)
    self.mox.StubOutWithMock(self.test_case.template, 'SetState')
    self.test_case.template.SetState(mox.IsA(unicode)).AndReturn(0)
    self.test_case.template.SetState(mox.IsA(str), append=True).AndReturn(0)

    self.mox.ReplayAll()
    self.assertRaisesRegexp(FactoryTestFailure,
                            '^user code and group code should not be the same$',
                            self.write_vpd_task.Run)

if __name__ == '__main__':
  unittest.main()
