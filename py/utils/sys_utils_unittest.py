#!/usr/bin/env python3
#
# Copyright 2014 The Chromium OS Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Unit tests for sys_utils module."""

import os
import subprocess
import tempfile
import unittest
from unittest import mock

from cros.factory.device import device_utils
from cros.factory.utils.process_utils import Spawn
from cros.factory.utils import sys_utils

SAMPLE_INTERRUPTS = """           CPU0       CPU1       CPU2       CPU3
  0:        124          0          0          0   IO-APIC-edge      timer
  1:         19        683          7         14   IO-APIC-edge      i8042
NMI:        612        631        661        401   Non-maskable interrupts
SPU:          0          0          0          0   Spurious interrupts"""


class GetInterruptsTest(unittest.TestCase):
  """Unit tests for GetInterrupts."""

  @mock.patch('cros.factory.utils.file_utils.ReadLines')
  def testGetCount(self, read_lines_mock):
    read_lines_mock.return_value = SAMPLE_INTERRUPTS.split('\n')

    ints = sys_utils.GetInterrupts()
    # Digit-type interrupts:
    self.assertEqual(ints['0'], 124)
    self.assertEqual(ints['1'], 19 + 683 + 7 + 14)

    # String-type interrupts:
    self.assertEqual(ints['NMI'], 612 + 631 + 661 + 401)
    self.assertEqual(ints['SPU'], 0)

    read_lines_mock.assert_called_once_with('/proc/interrupts')

  @mock.patch('cros.factory.utils.file_utils.ReadLines')
  def testFailToReadProcInterrupts(self, read_lines_mock):
    read_lines_mock.return_value = None

    self.assertRaisesRegex(
        OSError, r'Unable to read /proc/interrupts',
        sys_utils.GetInterrupts)

    read_lines_mock.assert_called_once_with('/proc/interrupts')


SAMPLE_INPUT_DEVICES = """I: Bus=0019 Vendor=0000 Product=0005 Version=0000
N: Name="Lid Switch"
P: Phys=PNP0C0D/button/input0
S: Sysfs=/devices/LNXSYSTM:00/device:00/PNP0C0D:00/input/input0
U: Uniq=
H: Handlers=lid_event_handler lid_event_handler event0
B: PROP=0
B: EV=21
B: SW=1

I: Bus=0019 Vendor=0000 Product=0001 Version=0000
N: Name="Power Button"
P: Phys=PNP0C0C/button/input0
S: Sysfs=/devices/LNXSYSTM:00/device:00/PNP0C0C:00/input/input1
U: Uniq=
H: Handlers=kbd event1
B: PROP=0
B: EV=3
B: KEY=10000000000000 0

I: Bus=0019 Vendor=0000 Product=0001 Version=0000
N: Name="Power Button"
P: Phys=LNXPWRBN/button/input0
S: Sysfs=/devices/LNXSYSTM:00/LNXPWRBN:00/input/input2
U: Uniq=
H: Handlers=kbd event2
B: PROP=0
B: EV=3
B: KEY=10000000000000 0

I: Bus=0011 Vendor=0001 Product=0001 Version=ab83
N: Name="AT Translated Set 2 keyboard"
P: Phys=isa0060/serio0/input0
S: Sysfs=/devices/platform/i8042/serio0/input/input3
U: Uniq=
H: Handlers=sysrq kbd event3
B: PROP=0
B: EV=120013
B: KEY=400402000000 3803078f800d001 feffffdfffefffff fffffffffffffffe
B: MSC=10
B: LED=7

I: Bus=0018 Vendor=0000 Product=0000 Version=0000
N: Name="Atmel maXTouch Touchscreen"
P: Phys=i2c-3-004a/input0
S: Sysfs=/devices/platform/80860F41:03/i2c-3/3-004a/input/input4
U: Uniq=
H: Handlers=event4
B: PROP=0
B: EV=b
B: KEY=400 0 0 0 0 0
B: ABS=661800001000003

I: Bus=0018 Vendor=0000 Product=0000 Version=0000
N: Name="Atmel maXTouch Touchpad"
P: Phys=i2c-0-004b/input0
S: Sysfs=/devices/platform/80860F41:00/i2c-0/0-004b/input/input5
U: Uniq=
H: Handlers=event5
B: PROP=5
B: EV=b
B: KEY=e520 10000 0 0 0 0
B: ABS=661800001000003

I: Bus=0000 Vendor=0000 Product=0000 Version=0000
N: Name="HDA Intel HDMI"
P: Phys=ALSA
S: Sysfs=/devices/pci0000:00/0000:00:1b.0/sound/card1/input6
U: Uniq=
H: Handlers=event6
B: PROP=0
B: EV=21
B: SW=140

I: Bus=0000 Vendor=0000 Product=0000 Version=0000
N: Name="HDA Intel HDMI"
P: Phys=ALSA
S: Sysfs=/devices/pci0000:00/0000:00:1b.0/sound/card1/input7
U: Uniq=
H: Handlers=event7
B: PROP=0
B: EV=21
B: SW=140
"""


class GetI2CBusTest(unittest.TestCase):
  """Unit tests for GetI2CBus."""

  @mock.patch('cros.factory.utils.file_utils.ReadFile')
  def testTouchpad(self, read_file_mock):
    read_file_mock.return_value = SAMPLE_INPUT_DEVICES
    self.assertEqual(sys_utils.GetI2CBus(['Dummy device name',
                                          'Atmel maXTouch Touchpad']), 0)
    read_file_mock.assert_called_once_with('/proc/bus/input/devices')

  @mock.patch('cros.factory.utils.file_utils.ReadFile')
  def testTouchscreen(self, read_file_mock):
    read_file_mock.return_value = SAMPLE_INPUT_DEVICES
    self.assertEqual(sys_utils.GetI2CBus(['Atmel maXTouch Touchscreen']), 3)
    read_file_mock.assert_called_once_with('/proc/bus/input/devices')

  @mock.patch('cros.factory.utils.file_utils.ReadFile')
  def testNoMatch(self, read_file_mock):
    read_file_mock.return_value = SAMPLE_INPUT_DEVICES
    self.assertEqual(sys_utils.GetI2CBus(['Unknown Device']), None)
    read_file_mock.assert_called_once_with('/proc/bus/input/devices')

  @mock.patch('cros.factory.utils.file_utils.ReadFile')
  def testNonI2CDevice(self, read_file_mock):
    read_file_mock.return_value = SAMPLE_INPUT_DEVICES
    self.assertEqual(sys_utils.GetI2CBus(['Lid Switch']), None)
    read_file_mock.assert_called_once_with('/proc/bus/input/devices')


SAMPLE_PARTITIONS = """major minor  #blocks  name

   7        0     313564 loop0
 179        0   15388672 mmcblk0
 179        1   11036672 mmcblk0p1
 179        2      16384 mmcblk0p2
 179        3    2097152 mmcblk0p3
 179        4      16384 mmcblk0p4
 179        5    2097152 mmcblk0p5
 179        6          0 mmcblk0p6
 179        7          0 mmcblk0p7
 179        8      16384 mmcblk0p8
 179        9          0 mmcblk0p9
 179       10          0 mmcblk0p10
 179       11       8192 mmcblk0p11
 179       12      16384 mmcblk0p12
 179       32       4096 mmcblk0boot1
 179       16       4096 mmcblk0boot0
 254        0    1048576 dm-0
 254        1     313564 dm-1
 253        0    1953128 zram0"""


class GetPartitionsTest(unittest.TestCase):
  """Unit tests for GetInterrupts."""

  @mock.patch('cros.factory.utils.file_utils.ReadLines')
  def testGetPartitions(self, read_lines_mock):
    read_lines_mock.return_value = SAMPLE_PARTITIONS.split('\n')

    partitions = sys_utils.GetPartitions()
    for p in partitions:
      print(str(p))

    read_lines_mock.assert_called_once_with('/proc/partitions')


class MountDeviceAndReadFileTest(unittest.TestCase):
  """Unittest for MountDeviceAndReadFile."""

  def setUp(self):
    # Creates a temp file and create file system on it as a mock device.
    self.device = tempfile.NamedTemporaryFile(prefix='MountDeviceAndReadFile')  # pylint: disable=consider-using-with
    Spawn(['truncate', '-s', '1M', self.device.name], log=True,
          check_call=True)

    # In CrOS chroot, mkfs and mkfs.extX may live in different locations that
    # normal user can't run without adding /sbin and /usr/sbin.
    env = os.environ.copy()
    env['PATH'] = '/sbin:/usr/sbin:' + env['PATH']
    Spawn(['/sbin/mkfs', '-E', 'root_owner=%d:%d' % (os.getuid(), os.getgid()),
           '-F', '-t', 'ext3', self.device.name], log=True, check_call=True,
          env=env)

    # Creates a file with some content on the device.
    mount_point = tempfile.mkdtemp(prefix='MountDeviceAndReadFileSetup')
    Spawn(['mount', self.device.name, mount_point], sudo=True, check_call=True,
          log=True)
    self.content = 'file content'
    self.file_name = 'file'
    with open(os.path.join(mount_point, self.file_name), 'w') as f:
      f.write(self.content)
    Spawn(['umount', '-l', mount_point], sudo=True, check_call=True, log=True)
    os.rmdir(mount_point)
    self.dut = device_utils.CreateDUTInterface()

    # Since 'mount', 'umount' requires root privilege, make link.Shell function
    # executes commands as root.
    # The reason why we don't use 'sudo' in MountPartition() is to make our code
    # more general. Because some Android devices don't have 'sudo'.
    def _SudoShell(command, stdin=None, stdout=None, stderr=None, cwd=None,
                   encoding='utf-8'):
      if isinstance(command, str):
        command = ['sudo', 'sh', '-c', command]
      else:
        command = ['sudo'] + command
      return subprocess.Popen(command, cwd=cwd, close_fds=True, stdin=stdin,
                              stdout=stdout, stderr=stderr, encoding=encoding)
    self.dut.link.Shell = _SudoShell

  def tearDown(self):
    self.device.close()

  def testMountDeviceAndReadFile(self):
    self.assertEqual(
        self.content,
        sys_utils.MountDeviceAndReadFile(
            self.device.name, self.file_name))

  def testMountDeviceAndReadFileWrongFile(self):
    with self.assertRaises(IOError):
      sys_utils.MountDeviceAndReadFile(self.device.name, 'no_file')

  def testMountDeviceAndReadFileWrongDevice(self):
    with self.assertRaises(Exception):
      sys_utils.MountDeviceAndReadFile('no_device', self.file_name)

  def testMountDeviceAndReadFileWithDUT(self):
    self.assertEqual(
        self.content,
        sys_utils.MountDeviceAndReadFile(
            self.device.name, self.file_name, self.dut))

  def testMountDeviceAndReadFileWrongFileWithDUT(self):
    with self.assertRaises(IOError):
      sys_utils.MountDeviceAndReadFile(self.device.name, 'no_file', self.dut)

  def testMountDeviceAndReadFileWrongDeviceWithDUT(self):
    with self.assertRaises(Exception):
      sys_utils.MountDeviceAndReadFile('no_device', self.file_name, self.dut)


class TestLogMessagesTest(unittest.TestCase):

  def testGetVarLogMessages(self):
    with tempfile.NamedTemporaryFile('w', encoding='utf-8') as f:
      data = ("Captain's log.\xFF\n"  # \xFF = invalid UTF-8
              'We are in pursuit of a starship of Ferengi design.\n')
      f.write(('X' * 100) + '\n' + data)
      f.flush()
      # Use max_length=len(data) + 5 so that we'll end up reading
      # (and discarding) the last 5 bytes of garbage X's.
      self.assertEqual(
          '<truncated 101 bytes>\n'
          "Captain's log.\xFF\n"
          'We are in pursuit of a starship of Ferengi design.\n',
          sys_utils.GetVarLogMessages(max_length=(len(data) + 5), path=f.name))

      dut = device_utils.CreateDUTInterface(board_class='LinuxBoard')
      self.assertEqual(
          '<truncated 101 bytes>\n'
          "Captain's log.\xFF\n"
          'We are in pursuit of a starship of Ferengi design.\n',
          sys_utils.GetVarLogMessages(
              max_length=(len(data) + 5), path=f.name, dut=dut))

  def testGetVarLogMessagesBeforeReboot(self):
    EARLIER_VAR_LOG_MESSAGES = (
        "19:26:17 kernel: That's all, folks.\n"
        "19:26:56 kernel: [  0.000000] Initializing cgroup subsys cpuset\n"
        "19:26:56 kernel: [  0.000000] Initializing cgroup subsys cpu\n"
        "19:26:56 kernel: [  0.000000] Linux version blahblahblah\n")

    VAR_LOG_MESSAGES = (
        "19:00:00 kernel: 7 p.m. and all's well.\n"
        "19:27:17 kernel: That's all, folks.\n"
        "19:27:17 kernel: Kernel logging (proc) stopped.\n"
        "19:27:56 kernel: imklog 4.6.2, log source = /proc/kmsg started.\n"
        "19:27:56 rsyslogd: "
        '[origin software="rsyslogd" blahblahblah] (re)start\n'
        "19:27:56 kernel: [  0.000000] Initializing cgroup subsys cpuset\n"
        "19:27:56 kernel: [  0.000000] Initializing cgroup subsys cpu\n"
        "19:27:56 kernel: [  0.000000] Linux version blahblahblah\n"
        "19:27:56 kernel: [  0.000000] Command line: blahblahblah\n")

    dut = device_utils.CreateDUTInterface(board_class='LinuxBoard')

    with tempfile.NamedTemporaryFile('w') as f:
      f.write(VAR_LOG_MESSAGES)
      f.flush()

      self.assertEqual(
          ("19:27:17 kernel: That's all, folks.\n"
           "19:27:17 kernel: Kernel logging (proc) stopped.\n"
           "<after reboot, kernel came up at 19:27:56>\n"),
          sys_utils.GetVarLogMessagesBeforeReboot(
              path=f.name, lines=2, dut=dut))

      self.assertEqual(
          ("19:27:17 kernel: That's all, folks.\n"
           "19:27:17 kernel: Kernel logging (proc) stopped.\n"
           "<after reboot, kernel came up at 19:27:56>\n"),
          sys_utils.GetVarLogMessagesBeforeReboot(path=f.name, lines=2))

      self.assertEqual(
          ("19:27:17 kernel: Kernel logging (proc) stopped.\n"
           "<after reboot, kernel came up at 19:27:56>\n"),
          sys_utils.GetVarLogMessagesBeforeReboot(path=f.name, lines=1))

      self.assertEqual(
          ("19:00:00 kernel: 7 p.m. and all's well.\n"
           "19:27:17 kernel: That's all, folks.\n"
           "19:27:17 kernel: Kernel logging (proc) stopped.\n"
           "<after reboot, kernel came up at 19:27:56>\n"),
          sys_utils.GetVarLogMessagesBeforeReboot(path=f.name, lines=100))

    with tempfile.NamedTemporaryFile('w') as f:
      f.write(EARLIER_VAR_LOG_MESSAGES)
      f.flush()
      self.assertEqual(
          ("19:26:17 kernel: That's all, folks.\n"
           "<after reboot, kernel came up at 19:26:56>\n"),
          sys_utils.GetVarLogMessagesBeforeReboot(path=f.name, lines=1))

class TestGetRunningFactoryPythonArchivePath(unittest.TestCase):

  def setUp(self):
    self.path_exists_mapping = {}
    self.original_path_exists_func = os.path.exists

  def path_exists_mock_side_effect(self, *args, **unused_kwargs):
    if args[0] in self.path_exists_mapping:
      return self.path_exists_mapping[args[0]]
    return self.original_path_exists_func(args[0])

  def testNotInPythonArchive(self):
    sys_utils.__file__ = '/path/to/factory/utils/sys_utils.py'
    self.path_exists_mapping = {
        sys_utils.__file__: True
    }

    with mock.patch('os.path.exists') as path_exists_mock:
      path_exists_mock.side_effect = self.path_exists_mock_side_effect
      self.assertEqual(sys_utils.GetRunningFactoryPythonArchivePath(), None)

  def testInPythonFactoryArchive(self):
    factory_par = '/path/to/factory.par'
    sys_utils.__file__ = '/path/to/factory.par/cros/factory/utils/sys_utils.py'
    self.path_exists_mapping = {
        sys_utils.__file__: False,
        factory_par: True
    }

    with mock.patch('os.path.exists') as path_exists_mock:
      path_exists_mock.side_effect = self.path_exists_mock_side_effect
      self.assertEqual(sys_utils.GetRunningFactoryPythonArchivePath(),
                       factory_par)

  def testNonExistingFileWithoutCrosFactoryPrefix(self):
    sys_utils.__file__ = '/path/to/nowhere/utils/sys_utils.py'
    self.path_exists_mapping = {
        sys_utils.__file__: False
    }

    with mock.patch('os.path.exists') as path_exists_mock:
      path_exists_mock.side_effect = self.path_exists_mock_side_effect
      self.assertEqual(sys_utils.GetRunningFactoryPythonArchivePath(), None)

  def testNonExistingFactoryPythonArchive(self):
    factory_par = '/path/to/factory.par'
    sys_utils.__file__ = '/path/to/factory.par/cros/factory/utils/sys_utils.py'
    self.path_exists_mapping = {
        sys_utils.__file__: False,
        factory_par: False
    }

    with mock.patch('os.path.exists') as path_exists_mock:
      path_exists_mock.side_effect = self.path_exists_mock_side_effect
      self.assertEqual(sys_utils.GetRunningFactoryPythonArchivePath(), None)


CGPT_SAMPLE_OUTPUT = """
Drive details:
    Total Size (bytes): 127984992256
    LBA Size (bytes): 4096
    Drive Size (blocks): 31246336

       start        size    part  contents
           0           1          PMBR (Boot GUID: D5B4458A-B127-D34E-8820-1FBB3FEEAA88)
           1           1          Pri GPT header
                                  Sig: [EFI PART]
                                  Rev: 0x00010000
                                  Size: 92 (blocks)
                                  Header CRC: 0x14c48cd5
                                  My LBA: 1
                                  Alternate LBA: 31246335
                                  First LBA: 6
                                  Last LBA: 31246330
                                  Disk UUID: 39FE81ED-928D-0D41-AC4D-0F6B816F4D9A
                                  Entries LBA: 2
                                  Number of entries: 128
                                  Size of entry: 128
                                  Entries CRC: 0x921998af
           2           4          Pri GPT table
     2134528    29111802       1  Label: "STATE"
                                  Type: Linux data
                                  UUID: 8C610EB9-6A82-5C41-8CF5-1B1F7162923F
          13        8192       2  Label: "KERN-A"
                                  Type: ChromeOS kernel
                                  UUID: EC401A47-F323-DC43-ACF8-5415F5842A32
                                  Attr: priority=1 tries=0 successful=1
     1085952     1048576       3  Label: "ROOT-A"
                                  Type: ChromeOS rootfs
                                  UUID: 4634AD6A-F583-3646-9A44-E20471C26FB5
        8205        8192       4  Label: "KERN-B"
                                  Type: ChromeOS kernel
                                  UUID: 0F6AB729-FDFA-844D-AE42-DFD4920E2E13
                                  Attr: priority=0 tries=15 successful=0
       37376     1048576       5  Label: "ROOT-B"
                                  Type: ChromeOS rootfs
                                  UUID: D7C108B7-931C-684F-B252-AB3692F4EE34
           9           1       6  Label: "KERN-C"
                                  Type: ChromeOS kernel
                                  UUID: 71BE9DF5-836A-5740-9083-E3039D250913
                                  Attr: priority=0 tries=15 successful=0
          10           1       7  Label: "ROOT-C"
                                  Type: ChromeOS rootfs
                                  UUID: 52A7CF50-31F8-B24D-8A00-E924908765C6
       16896        4096       8  Label: "OEM"
                                  Type: Linux data
                                  UUID: 6ADE7ECA-B0F2-2842-BD5D-DD38D1D3A4BD
          11           1       9  Label: "reserved"
                                  Type: ChromeOS reserved
                                  UUID: 5117BE06-FCA8-214E-B00A-0AC53AA64F1C
          12           1      10  Label: "reserved"
                                  Type: ChromeOS reserved
                                  UUID: 5C2A7CBA-6B8E-374E-A774-6DDAE421EB3F
           8           1      11  Label: "RWFW"
                                  Type: ChromeOS firmware
                                  UUID: 43FE83AA-3E7E-C446-8303-29FED184335C
       20992       16384      12  Label: "EFI-SYSTEM"
                                  Type: EFI System Partition
                                  UUID: D5B4458A-B127-D34E-8820-1FBB3FEEAA88
                                  Attr: legacy_boot=1
    31246331           4          Sec GPT table
    31246335           1          Sec GPT header
"""


class TestPartitionManagerGetSectorSize(unittest.TestCase):

  @mock.patch('cros.factory.device.device_utils.CreateDUTInterface')
  def testCGPT(self, mock_dut):
    mock_dut.link.IsLocal.return_value = False
    mock_dut.Call.return_value = 0
    mock_dut.CheckOutput.return_value = CGPT_SAMPLE_OUTPUT
    manager = sys_utils.PartitionManager('mock_dev', mock_dut)

    self.assertEqual(manager.GetSectorSize(), 4096)

if __name__ == '__main__':
  unittest.main()
