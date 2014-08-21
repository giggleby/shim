# -*- mode: python; coding: utf-8 -*-
#
# Copyright (c) 2013 The Chromium OS Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.


"""The AP test list.
"""


import hashlib
import logging
import glob

import factory_common  # pylint: disable=W0611
from cros.factory.test import utils
from cros.factory.test.test_lists.test_lists import OperatorTest
from cros.factory.test.test_lists.test_lists import SamplingRate
from cros.factory.test.test_lists.test_lists import TestList
from cros.factory.test.test_lists.test_lists import WLAN
from cros.factory.test.test_lists.test_lists import TestGroup
from cros.factory.test.test_lists.test_lists import AutomatedSequence
from cros.factory.test.test_lists.test_lists import FactoryTest
from cros.factory.test.test_lists.test_lists import HaltStep
from cros.factory.test.test_lists.test_lists import OperatorTest
from cros.factory.test.test_lists.test_lists import Passed
from cros.factory.test.test_lists.test_lists import RebootStep
from cros.factory.test.test_lists.test_lists import TestGroup

HOURS = 60 * 60
MINUTES = 60


class TestListArgs(object):
  """A helper object used to construct a single test list.

  This may contain:

  - arguments used when constructing the test list
  - common dargs or values that are shared across different tests
  - helper methods use to construct tests based on test arguments

  Nothing in this class is used by the test harness directly, rather
  only used by this file when constructing the test list.
  """
  # Current build phase.  Various properties such as write protection
  # are double-checked in certain tests based on the value of this
  # argument; search throughout the repo for "AssertStartingAtPhase"
  # for details.
  #
  # - PROTO = prototype build (most forgiving; can be used for testing)
  # - EVT = first build with plastics
  # - DVT = second build with plastics
  # - PVT_DOGFOOD = production of salable units, except that write protection
  #   may be disabled.  These are suitable for internal "dogfood" testing
  #   (http://goo.gl/iU8vlW), but non-write-protected devices may not actually
  #   be sold.
  # - PVT = production of salable units
  phase = 'PROTO'

  # Enable options that apply only in a real factory environment.
  factory_environment = False

  # Enable shopfloor. Note that some factory environment might
  # not need a shopfloor.
  enable_shopfloor = False

  # Enable fixute tests if fixtures are available.
  enable_fixture_tests = True

  # Enable/Disable flush event logs in foreground.
  # This is used in SyncShopFloor and Finalize.
  enable_flush_event_logs = True

  # Whether to check for a completed netboot factory install.
  # Disable it for preflash image.
  check_factory_install_complete = False

  # Whether the device is fully imaged (and has the normal partition
  # table).
  fully_imaged = False

  # Host/port for shopfloor communication.
  # shopfloor_host = '10.3.0.11'
  # shopfloor_port = 8082

  # Whether barriers should be enabled.
  enable_barriers = True


  def SyncShopFloor(self, id_suffix=None, update_without_prompt=False,
                    flush_event_logs=None, run_if=None):
    """Creates a step to sync with the shopfloor server.

    If factory_environment is False, None is returned (since there is no
    shopfloor server to sync to).

    Args:
      id_suffix: An optional suffix in case multiple SyncShopFloor steps
        are needed in the same group (since they cannot have the same ID).
      update_without_prompt: do factory update if needed without prompt.
      flush_event_logs: Flush event logs to shopfloor. The default value is
        enable_flush_event_logs in TestListArgs.
      run_if: run_if argument passed to OperatorTest.
    """
    if not self.factory_environment:
      return

    if flush_event_logs is None:
      flush_event_logs = self.enable_flush_event_logs

    suffix_str = str(id_suffix) if id_suffix else ''
    OperatorTest(
        id='SyncShopFloor' + suffix_str,
        pytest_name='flush_event_logs',
        label_zh=u'同步事件记录 ' + suffix_str,
        run_if=run_if,
        dargs=dict(
            update_without_prompt=update_without_prompt,
            sync_event_logs=flush_event_logs))

  def Barrier(self, id_suffix, pass_without_prompt=False,
              accessibility=False, charge_manager=True, run_if=None):
    """Test barrier to display test summary.

    Args:
      id_suffix: The id suffix after 'Barrier'.
      pass_without_prompt: Pass barrier without prompt.
      accessibility: To show the message with clear color.
      charge_manager: Enable/disable charge manager.
      run_if: run_if argument passed to OperatorTest.
    """
    if self.enable_barriers:
      OperatorTest(
          id='Barrier' + str(id_suffix),
          label_zh=u'检查关卡' + str(id_suffix),
          has_automator=True,
          pytest_name='summary',
          run_if=run_if,
          never_fails=True,
          disable_abort=True,
          exclusive=None if charge_manager else ['CHARGER'],
          dargs=dict(
              disable_input_on_fail=True,
              pass_without_prompt=pass_without_prompt,
              accessibility=accessibility))


def SetOptions(options, args):
  """Sets test list options for goofy.

  The options in this function will be used by test harness(goofy).
  Note that this function is shared by different test lists so
  users can set default options here for their need.
  For details on available options, see the Options class in
  py/test/factory.py.
  After calling this function, user can still modify options for different
  test list. For example, set options.engineering_password_sha1 to '' to
  enable engineering mode in experiment test list.

  Args:
    options: The options attribute of the TestList object to be constructed.
      Note that it will be modified in-place in this method.
    args: A TestListArgs object which contains argument that are used commonly
      by tests and options. Fox example min_charge_pct, max_charge_pct,
      shopfloor_host.
  """

  # Require explicit IDs for each test
  options.strict_ids = True

  options.phase = args.phase

  if args.factory_environment:
    # echo -n 'passwordgoeshere' | sha1sum
    # Use operator mode by default and require a password to enable
    # engineering mode. This password is 'cros'.
    options.engineering_password_sha1 = ('8c19cad459f97de3f8c836c794d9a0060'
        'a795d7b')

    # - Default to Chinese language
    options.ui_lang = 'zh'

    # Enable/Disable background event log syncing
    # Set to None or 0 to disable it.
    options.sync_event_log_period_secs = 0
    options.update_period_secs = 5 * MINUTES
    # - Enable clock syncing with shopfloor server
    options.sync_time_period_secs = None
    options.shopfloor_server_url = 'http://%s:%d/' % (
        args.shopfloor_host, args.shopfloor_port)
    # - Disable ChromeOS keys.
    options.disable_cros_shortcut_keys = True

    # Enable/Disable system log syncing
    options.enable_sync_log = True
    options.sync_log_period_secs = 10 * MINUTES
    options.scan_log_period_secs = 2 * MINUTES
    options.core_dump_watchlist = []
    options.log_disk_space_period_secs = 2 * MINUTES
    options.check_battery_period_secs = 2 * MINUTES
    options.warning_low_battery_pct = 10
    options.critical_low_battery_pct = 5
    options.stateful_usage_threshold = 90


def CreateExperimentTestList():
  """Creates an experiment test list.

  This is a place holder for experiment test list. User can modify this
  function to suit the need.
  In this example this method creates an experiment test list containing
  Experiment tests defined in generic_experiment. Also, the test list contains
  RunIn tests defined in generic_run_in. Also, note that the
  TestListArgs object args and test_list.options are modified for experiment.
  """
  args = TestListArgs()
  args.factory_environment = False
  args.enable_shopfloor = False
  args.fully_imaged = False

  with TestList('ap_test', 'AP Test') as test_list:
    SetOptions(test_list.options, args)
    test_list.options.clear_state_on_start = False
    test_list.options.auto_run_on_start = True
    # itspeter_hack: no effect ?
    # test_list.options.auto_run_on_keypress = True

    test_list.options.stop_on_failure = True
    test_list.options.engineering_password_sha1 = None
    test_list.options.ui_lang = 'en'
    test_list.options.enable_shopfloor = False
    test_list.options.enable_charge_manager = False
    test_list.options.use_cpufreq_manager = False

    Experiment(args)


def CreateTestLists():
  """Creates test list.

  This is the external interface to test list creation (called by the
  test list builder).  This function is required and its name cannot
  be changed.
  """
  CreateExperimentTestList()


def Experiment(args):
  """Creates Experiment test list.

  Args:
    args: A TestListArgs object.
  """
  with TestGroup(id='Manual', label_zh=u'人員手動操作'):
    OperatorTest(
        id='ScanPcbSN',
        label_zh=u'掃描主板序號',
        pytest_name='scan',
        dargs=dict(
            ro_vpd_key='mlb_sn',
            event_log_key='mlb_sn',
            #regexp=r'.*',
            regexp=r'^STRMBFSJ\d{8}$',
            label_en='Scan PCB Serial Number',
            label_zh='掃描主板序號'))

    OperatorTest(
        id='ScanPrimaryMAC',
        label_zh=u'掃描主要MAC',
        pytest_name='scan',
        dargs=dict(
            #ro_vpd_key='eth?_mac',
            ro_vpd_key='ethernet_mac?',
            event_log_key='primary_mac',
            mac_extend=4,
            #regexp=r'.*',
            regexp=r'^[0-9a-fA-F]{2}:[0-9a-fA-F]{2}:[0-9a-fA-F]{2}:[0-9a-fA-F]{2}:[0-9a-fA-F]{2}:[0-9a-fA-F]{2}$',
            label_en='Scan Primary MAC address',
            label_zh='掃描主要MAC address'))

  with TestGroup(id='Auomated', label_zh=u'全自動化測試'):
    OperatorTest(
        id='TestPCIE',
        label_zh=u'測試PCI匯流排',
        pytest_name='run_scripts',
        dargs=dict(
           script_path='/etc/init/sh/check-pci.sh'))

    OperatorTest(
        id='Test2G',
        label_zh=u'測試2.4G連線能力',
        pytest_name='run_scripts',
        dargs=dict(
           script_path='/etc/init/sh/2g-associate-belkin.sh',
           arguments=['test']))

    OperatorTest(
        id='Test5G',
        label_zh=u'測試5G連線能力',
        pytest_name='run_scripts',
        dargs=dict(
           script_path='/etc/init/sh/5g-associate-belkin.sh',
           arguments=['test']))

    OperatorTest(
        id='StressAppTest',
        label_zh=u'压力测试',
        autotest_name='hardware_SAT',
        # For 100 secs.
        # Completed: 218580.00M in 100.01s 2185.59MB/s
        dargs=dict(
            seconds=100,  # TODO(itspeter): Decide the timing
            drop_caches=True,
            free_memory_fraction=0.75,  # TODO(itspeter): Decide the ratio
            wait_secs=0,
            disk_thread=False))  # TODO(itspeter): Enable after eMMC is stable

    #OperatorTest(
    #    id='FlashFirmwareFromLocal',
    #    label_zh=u'FlashfirmwareFromLocal',
    #    pytest_name='run_scripts',
    #    dargs=dict(
    #       script_path='/etc/init/sh/flash-firmware.sh',
    #       arguments=['/etc/init/fw/fw.0x42208000.0913.2014.2008.bin']))

    OperatorTest(
        id='FlashFirmwareFromFTP',
        label_zh=u'FlashfirmwareFromFTP',
        pytest_name='run_scripts',
        dargs=dict(
           script_path='/etc/init/sh/flash-firmware-from-ftp.sh',
           arguments=['Upgrade_FW_200x.bin',
                      'b7da97f9af00ccc0744693482633ee47']))

    OperatorTest(
        id='Install314ToEmmcFromFTP',
        label_zh=u'Install314ToEmmcFromFTP',
        pytest_name='run_scripts',
        dargs=dict(
           script_path='/etc/init/sh/install_eMMC_from_ftp.sh',
           arguments=['eMMC_chromeos_install_314.bin'],
           display='/tmp/pv.log'))

    #OperatorTest(
    #    id='InstallUsbToEmmc',
    #    label_zh=u'InstallUSBToEmmc',
    #    pytest_name='run_scripts',
    #    dargs=dict(
    #       script_path='/etc/init/sh/install_eMMC_in_factory.sh'))

    #OperatorTest(
    #    id='ScanEth1',
    #    label_zh=u'ETH 1 MAC address',
    #    pytest_name='scan',
    #    dargs=dict(
    #        ro_vpd_key='eth1_mac',
    #        event_log_key='eth1_mac',
    #        label_en='Scan ETH 1 MAC address',
    #        label_zh='Scan ETH 1 MAC address',
    #        regexp=r'.*'))

    #OperatorTest(
    #    id='ScanEth2',
    #    label_zh=u'ETH 2 MAC address',
    #    pytest_name='scan',
    #    dargs=dict(
    #        ro_vpd_key='eth2_mac',
    #        event_log_key='eth2_mac',
    #        label_en='Scan ETH 2 MAC address',
    #        label_zh='Scan ETH 2 MAC address',
    #        regexp=r'.*'))

    #OperatorTest(
    #    id='ScanEth3',
    #    label_zh=u'ETH 3 MAC address',
    #    pytest_name='scan',
    #    dargs=dict(
    #        ro_vpd_key='eth3_mac',
    #        event_log_key='eth3_mac',
    #        label_en='Scan ETH 3 MAC address',
    #        label_zh='Scan ETH 3 MAC address',
    #        regexp=r'.*'))
