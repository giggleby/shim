#!/usr/bin/env python3
#
# Copyright 2023 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

import logging
import os
import sys
import unittest
from unittest import mock

import minijail0


class Minijail0Test(unittest.TestCase):

  def setUp(self):
    logging.disable()
    mock.patch.object(logging, 'basicConfig', autospec=True).start()
    self.exit = mock.patch.object(sys, 'exit', autospec=True).start()
    self.execvp = mock.patch.object(os, 'execvp', autospec=True).start()
    self.fork = mock.patch.object(os, 'fork', autospec=True).start()
    self.addCleanup(mock.patch.stopall)

  def testUnsupportedArgs_NoJailBreak(self):
    args_input = [
        '/sbin/minijail0',
        '--config=/usr/share/minijail/oobe_config_restore.conf',
        '/usr/sbin/oobe_config_restore'
    ]

    minijail0.Main(args_input)

    self.execvp.assert_called_once_with('/run/jailed/minijail0', [
        '/run/jailed/minijail0',
        '--config=/usr/share/minijail/oobe_config_restore.conf',
        '/usr/sbin/oobe_config_restore'
    ])

  def testNotAllowedProgram_NoJailBreak(self):
    args_input = [
        '/sbin/minijail0',
        '/bin/ls',
    ]

    minijail0.Main(args_input)

    self.execvp.assert_called_once_with('/run/jailed/minijail0',
                                        ['/run/jailed/minijail0', '/bin/ls'])

  # Source: chromeos-base/arc-sslh-init/files/upstart/sslh.conf
  shared_allowed_program_input = [
      'minijail0',
      '-i',
      '-I',
      '-p',
      '-l',
      '-N',
      '-r',
      '-v',
      '-w',
      '--uts',
      '-P /mnt/empty',
      '--mount-dev',
      '-b',
      '/,/',
      '-b',
      '/proc,/proc',
      '-b',
      '/dev/log,/dev/log',
      '-S',
      '/usr/share/policy/sslh-seccomp.policy',
      '--',
      '/usr/sbin/sslh-fork',
      '-F/etc/sslh.conf',
  ]

  def testAllowedProgram_Fork_ParentJailbreak(self):
    self.fork.return_value = 1

    minijail0.Main(self.shared_allowed_program_input)

    self.fork.assert_called_once_with()
    self.execvp.assert_called_once_with(
        '/usr/sbin/sslh-fork', ['/usr/sbin/sslh-fork', '-F/etc/sslh.conf'])

  def testAllowedProgram_Fork_ChildExit(self):
    self.fork.return_value = 0

    minijail0.Main(self.shared_allowed_program_input)

    self.fork.assert_called_once_with()
    self.exit.assert_called_once_with()

  def testAllowedProgram_NoFork_JailBreak(self):
    args_input = self.shared_allowed_program_input.copy()
    args_input.remove('-i')

    minijail0.Main(args_input)

    self.fork.assert_not_called()
    self.execvp.assert_called_once_with(
        '/usr/sbin/sslh-fork', ['/usr/sbin/sslh-fork', '-F/etc/sslh.conf'])

  def testAllowedProgram_UnknownException_exit1(self):
    self.fork.return_value = 1
    self.execvp.side_effect = Exception('OSError')

    minijail0.Main(self.shared_allowed_program_input)

    self.execvp.assert_called_once_with(
        '/usr/sbin/sslh-fork', ['/usr/sbin/sslh-fork', '-F/etc/sslh.conf'])
    self.exit.assert_called_once_with(1)


if __name__ == '__main__':
  unittest.main()
