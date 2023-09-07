#!/usr/bin/env python3
#
# Copyright 2023 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

import argparse
import subprocess

from cros.factory.tools import run_unittests


def main():
  parser = argparse.ArgumentParser(description='Show the coverage report.')
  parser.add_argument('--include', '-i', default='',
                      help='Only files matched the pattern will be reported.')
  args = parser.parse_args()

  excluded = ['*_unittest.py', '*/__init__.py']
  for e in run_unittests.TESTS_TO_EXCLUDE:
    if e.endswith('.py'):
      excluded.append(e)
    else:
      excluded.append(e + '/*')

  cmd = ['coverage', 'report', '--omit', ','.join(excluded)]
  if args.include:
    cmd += ['--include', args.include]

  subprocess.check_call(cmd)


if __name__ == '__main__':
  main()
