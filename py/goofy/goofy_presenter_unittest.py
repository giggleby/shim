#!/usr/bin/python -u
#
# -*- coding: utf-8 -*-
#
# Copyright (c) 2014 The Chromium OS Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.


"""The unittest for the presenter-side of the main factory test flow."""


import factory_common  # pylint: disable=W0611

import logging
import mox
import threading
import time
import unittest

from cros.factory.goofy.goofy_presenter import GoofyPresenter
from cros.factory.goofy import link_manager
from cros.factory.test import factory
from cros.factory.test.utils import dhcp_utils

_FAKE_MAC_ADDRESS = "FakeMacAddress"

class GoofyPresenterTest(unittest.TestCase):
  """Base class for GoofyPresenter test cases."""

  def setUp(self):
    dummy_server = dhcp_utils.DummyDHCPManager()
    link_manager.dhcp_utils.StartDHCPManager = lambda **kargs: dummy_server
    self.goofy = GoofyPresenter()
    self.goofy.link_manager.Start()

  def tearDown(self):
    self.goofy.destroy()

    # Make sure we're not leaving any extra threads hanging around
    # after a second.
    for _ in range(10):
      extra_threads = [t for t in threading.enumerate()
                       if t != threading.current_thread()]
      if not extra_threads:
        break
      logging.info("Waiting for %d threads to die", len(extra_threads))

      # Wait another 100 ms
      time.sleep(.1)

    self.assertEqual([], extra_threads)


class BasicSanityTest(GoofyPresenterTest):
  """Do nothing except invoke setup and teardown."""

  def runTest(self):
    self.assertIsNotNone(self.goofy)


class UIControlTest(GoofyPresenterTest):
  """Present UI according to connection status."""

  def runTest(self):
    m = mox.Mox()

    m.StubOutWithMock(self.goofy.ui_app_controller, "ShowUI")
    # Link manager has a special __getattr__ function, so we can't just stub
    # out a single function.
    old_link_manager = self.goofy.link_manager
    self.goofy.link_manager = m.CreateMockAnything()

    self.goofy.ui_app_controller.ShowUI("192.168.1.1",
                                        _FAKE_MAC_ADDRESS).AndReturn(True)

    self.goofy.ui_app_controller.ShowDisconnectedScreen(_FAKE_MAC_ADDRESS)

    self.goofy.ui_app_controller.ShowUI("192.168.1.1",
                                        _FAKE_MAC_ADDRESS).AndReturn(False)
    self.goofy.ui_app_controller.ShowUI("192.168.1.1",
                                        _FAKE_MAC_ADDRESS).AndReturn(True)

    m.ReplayAll()

    # DUT connected. GoofyPresenter shows the UI.
    self.goofy.DUTConnected("192.168.1.1", _FAKE_MAC_ADDRESS)
    # Now hide it.
    self.goofy.DUTDisconnected("192.168.1.1")

    # DUT connected again. This time, the UI fails to show at the first try.
    self.goofy.DUTConnected("192.168.1.1", _FAKE_MAC_ADDRESS)
    # Kick GoofyPresenter so that it retries
    self.goofy.run_once()
    time.sleep(0.3)
    # Kick GoofyPresenter again to make sure it stops retrying after the UI
    # shows successfully.
    self.goofy.run_once()
    time.sleep(0.3)

    m.UnsetStubs()
    self.goofy.link_manager = old_link_manager

    m.VerifyAll()


if __name__ == "__main__":
  factory.init_logging("goofy_presenter_unittest")
  unittest.main()
