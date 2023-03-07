# Copyright 2020 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Suspend and resume device with given cycles.

Description
-----------
Suspends and resumes the device an adjustable number of times for adjustable
random lengths of time.
See ``suspend_stress_test`` for more details.

Test Procedure
--------------
This is an automated test without user interaction.

When started, the test will try to suspend and resume by given arguments.
Will fail if unexpected reboot, crash or error found.

Dependency
----------
- power manager ``powerd``.
- power manager tool ``suspend_stress_test``.

Examples
--------
To suspend/resume in 1 cycle, suspend in 5~10 seconds, resume in 5~10 seconds,
and suspend to idle by writing freeze to ``/sys/power/state``::

  {
    "pytest_name": "suspend_stress"
  }
"""

import logging
import os
import re
import threading
import time
from typing import List, Optional

from cros.factory.device import device_types
from cros.factory.device import device_utils
from cros.factory.test.env import paths
from cros.factory.test import session
from cros.factory.test import state
from cros.factory.test import test_case
from cros.factory.test import test_ui
from cros.factory.testlog import testlog
from cros.factory.utils.arg_utils import Arg
from cros.factory.utils import file_utils
from cros.factory.utils import process_utils


_MIN_SUSPEND_MARGIN_SECS = 5
_WAKE_SOURCE_PATTERN = re.compile('|'.join((
    r'.*\| Wake Source \| .*$',
    r'.*\| EC Event \| AC Connected$',
    r'.*\| EC Event \| AC Disconnected$',
    r'.*\| EC Event \| Host Event Hang$',
    r'.*\| EC Event \| Key Pressed$',
    r'.*\| EC Event \| USB MUX change$',
)))


def GetElog(dut: device_types.DeviceBoard,
            cut_line: Optional[str] = None) -> List[str]:
  """Return elog.

  elog is a useful log to get the wake source.

  Args:
    dut: The device interface.
    cut_line: The last line of elog before we run suspend_stress_test. If it's
      specified and found in the logs, we only returns the line after that. If
      it's not found in the log, then elog is probably cleared so we return the
      whole section.

  Returns:
    The elog.
  """
  p = dut.Popen(['elogtool', 'list', '--utc'], stdout=dut.PIPE, stderr=dut.PIPE)
  stdout, unused_stderr = p.communicate()
  stdout_lines = stdout.splitlines()
  if cut_line:
    for index, line in enumerate(stdout_lines):
      if line == cut_line:
        stdout_lines = stdout_lines[index + 1:]
        break
  return stdout_lines


def GetElogLastLine(dut: device_types.DeviceBoard) -> Optional[str]:
  stdout_lines = GetElog(dut)
  return stdout_lines[-1] if stdout_lines else None


def GetWakeSource(elog: List[str]) -> Optional[str]:
  """Return wake source from the elog.

  The wake source may be wrong because elog doesn't create an event for some
  wake sources. For example, b/222375516.

  Args:
    elog: The content of elog.

  Returns:
    The line indicates the wake source.
  """
  wake_source = None
  for line in reversed(elog):
    match = _WAKE_SOURCE_PATTERN.match(line)
    if match:
      wake_source = match.group(0)
      break
  return wake_source


class SuspendStressTest(test_case.TestCase):
  """Run suspend_stress_test to test the suspending is fine."""

  ARGS = [
      Arg('cycles', int, 'Number of cycles to suspend/resume', default=1),
      Arg('suspend_delay_max_secs', int,
          'Max time in sec during suspend per cycle', default=10),
      Arg('suspend_delay_min_secs', int,
          'Min time in sec during suspend per cycle', default=5),
      Arg('resume_delay_max_secs', int,
          'Max time in sec during resume per cycle', default=10),
      Arg('resume_delay_min_secs', int,
          'Min time in sec during resume per cycle', default=5),
      Arg('suspend_time_margin_min_secs', int,
          'Min seconds of the (actual - expected) suspended time diff',
          default=0),
      Arg('suspend_time_margin_max_secs', int,
          'Max seconds of the (actual - expected) suspended time diff',
          default=30),
      Arg('ignore_wakeup_source', str, 'Wakeup source to ignore', default=None),
      Arg('backup_rtc', bool, 'Use second rtc if present for backup',
          default=False),
      Arg('memory_check', bool, 'Use memory_suspend_test to suspend',
          default=False),
      Arg('memory_check_size', int,
          'Amount of memory to allocate (0 means as much as possible)',
          default=0),
      Arg('fw_errors_fatal', bool, 'Abort on firmware errors', default=True),
      Arg('premature_wake_fatal', bool,
          'Abort on any premature wakes from suspend', default=True),
      Arg('late_wake_fatal', bool, 'Abort on any late wakes from suspend',
          default=True),
      Arg('pre_suspend_command', str, 'Command to run before each suspend',
          default=''),
      Arg('post_resume_command', str, 'Command to run after each resume',
          default=''),
  ]

  ui_class = test_ui.ScrollableLogUI

  def setUp(self):
    self.assertGreaterEqual(self.args.memory_check_size, 0)
    self.assertTrue(self.args.memory_check or not self.args.memory_check_size,
                    'Do not specify memory_check_size if memory_check is '
                    'False.')
    self.assertGreaterEqual(self.args.suspend_delay_min_secs,
                            _MIN_SUSPEND_MARGIN_SECS, 'The '
                            'suspend_delay_min_secs is too low, bad '
                            'test_list?')
    self.assertGreaterEqual(self.args.suspend_delay_max_secs,
                            self.args.suspend_delay_min_secs, 'Invalid suspend '
                            'timings provided in test_list (max < min).')
    self.assertGreaterEqual(self.args.resume_delay_max_secs,
                            self.args.resume_delay_min_secs, 'Invalid resume '
                            'timings provided in test_list (max < min).')
    self.dut = device_utils.CreateDUTInterface()
    self.goofy = state.GetInstance()
    self._suspend_stress_test_stop = threading.Event()

  def UpdateOutput(self, handle, interval_sec=0.1):
    """Updates output from file handle to given HTML node."""
    while not self._suspend_stress_test_stop.is_set():
      c = handle.read()
      if c:
        self.ui.AppendLog(c)
      time.sleep(interval_sec)

  def runTest(self):

    def GetLogPath(suffix):
      path = 'suspend_stress_test.' + suffix
      return os.path.join(paths.DATA_TESTS_DIR, session.GetCurrentTestPath(),
                          path)

    command = [
        'suspend_stress_test',
        '--count',
        str(self.args.cycles),
        '--suspend_max',
        str(self.args.suspend_delay_max_secs),
        '--suspend_min',
        str(self.args.suspend_delay_min_secs),
        '--wake_max',
        str(self.args.resume_delay_max_secs),
        '--wake_min',
        str(self.args.resume_delay_min_secs),
        '--suspend_time_margin_min',
        str(self.args.suspend_time_margin_min_secs),
        '--suspend_time_margin_max',
        str(self.args.suspend_time_margin_max_secs),
        f"--{'' if self.args.fw_errors_fatal else 'no'}fw_errors_fatal",
        f"--{'' if self.args.premature_wake_fatal else 'no'}"
        f"premature_wake_fatal",
        f"--{'' if self.args.late_wake_fatal else 'no'}late_wake_fatal",
        '--record_dmesg_dir',
        os.path.dirname(GetLogPath('')),
        '--pre_suspend_command',
        self.args.pre_suspend_command,
        '--post_resume_command',
        self.args.post_resume_command,
    ]
    if self.args.ignore_wakeup_source:
      command += ['--ignore_wakeup_source', self.args.ignore_wakeup_source]
    if self.args.backup_rtc:
      command += ['--backup_rtc']
    if self.args.memory_check:
      command += [
          '--memory_check',
          '--memory_check_size', str(self.args.memory_check_size)]

    logging.info('command: %r', command)
    testlog.LogParam('command', command)

    elog_cut_line = GetElogLastLine(self.dut)

    logging.info('Log path is %s', GetLogPath('*'))
    result_path = GetLogPath('result')
    stdout_path = GetLogPath('stdout')
    stderr_path = GetLogPath('stderr')
    with open(stdout_path, 'w+', 1, encoding='utf8') as out, open(
        stderr_path, 'w', 1, encoding='utf8') as err:
      process = self.dut.Popen(command, stdout=out, stderr=err)
      thread = process_utils.StartDaemonThread(
          target=self.UpdateOutput, args=(out, ))
      process.wait()
      self._suspend_stress_test_stop.set()
      thread.join()
    self.goofy.WaitForWebSocketUp()

    stdout = file_utils.ReadFile(stdout_path)
    stderr = file_utils.ReadFile(stderr_path)
    returncode = process.returncode

    try:
      file_utils.WriteFile(result_path, str(returncode))
    except IOError:
      logging.exception('Can not write logs to %s.', result_path)

    testlog.LogParam('stdout', stdout)
    testlog.LogParam('stderr', stderr)
    testlog.LogParam('returncode', returncode)
    # TODO(chuntsen): Attach EC logs and other system logs on failure.

    elog = GetElog(self.dut, elog_cut_line)
    testlog_elog = False
    errors = []
    if returncode != 0:
      errors.append(f'Suspend stress test failed: returncode:{int(returncode)}')
    match = re.findall(r'Premature wake detected', stdout)
    if match:
      testlog_elog = True
      wake_source = GetWakeSource(elog)
      if self.args.premature_wake_fatal:
        errors.append(f'Premature wake detected:{len(match)}')
        errors.append(f'Last elog Wake Source event: {wake_source!r}')
      else:
        logging.warning('Premature wake detected:%d', len(match))
        logging.warning('Last elog Wake Source event: %r', wake_source)
    match = re.findall(r'Late wake detected', stdout)
    if match:
      if self.args.late_wake_fatal:
        errors.append(f'Late wake detected:{len(match)}')
      else:
        logging.warning('Late wake detected:%d', len(match))
    match = re.search(r'Finished (\d+) iterations', stdout)
    if match and match.group(1) != str(self.args.cycles):
      errors.append(f'Only finished {match.group(1)!r} cycles instead of '
                    f'{int(self.args.cycles)} cycles')
    match = re.search(r'Suspend failures: (\d+)', stdout)
    if match and match.group(1) != '0':
      errors.append(match.group(0))
    match = re.search(r'Wakealarm errors: (\d+)', stdout)
    if match and match.group(1) != '0':
      errors.append(match.group(0))
    match = re.search(r'Firmware log errors: (\d+)', stdout)
    if match and match.group(1) != '0':
      if self.args.fw_errors_fatal:
        errors.append(match.group(0))
      else:
        logging.warning(match.group(0))
    match = re.search(r's0ix errors: (\d+)', stdout)
    if match and match.group(1) != '0':
      errors.append(match.group(0))
    if testlog_elog or errors:
      # This is the elog produced during the test.
      testlog.LogParam('elog', elog)
    if errors:
      self.FailTask(f'{errors!r}')
