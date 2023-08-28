#!/usr/bin/env python3
#
# Copyright 2023 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

import subprocess

from cros.factory.tools import run_unittests


def main():
  excluded = ['*_unittest.py', '*/__init__.py']
  for e in run_unittests.TESTS_TO_EXCLUDE:
    if e.endswith('.py'):
      excluded.append(e)
    else:
      excluded.append(e + '/*')

  subprocess.run(['coverage', 'combine'], check=True, stdout=subprocess.DEVNULL)
  subprocess.check_call(['coverage', 'report', '--omit', ','.join(excluded)])


if __name__ == '__main__':
  main()
