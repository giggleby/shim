#!/usr/bin/env python
#
# Copyright (c) 2012 The Chromium OS Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Analyzes test log of StressAppTest."""

import argparse
import glob
import re
import sys

TEST_FAIL_PATTERN = re.compile('END ERROR')
TEST_PASS_PATTERN = re.compile('END GOOD\s+\S+StressAppTest')
ERROR_PATTERN = re.compile('Hardware Error: miscompare.*' +
    'read:(0x[0-9a-f]+), reread:(0x[0-9a-f]+) expected:(0x[0-9a-f]+)')

DEFAULT_LOG_PATH = '/var/factory/tests/RunIn.Stress.StressAppTest/log'
LOG_SEARCH_GLOB = '/var/factory/tests/RunIn.Stress.StressAppTest-*/log'

def GetBadChipMask(xor_value):
  ret = 0
  for i in xrange(4):
    mask = (0xffff << (16 * i))
    if xor_value & mask:
      ret |= (1 << i)
  return ret

def CheckPassed(log):
  return TEST_PASS_PATTERN.search(log)

def CheckFailed(log):
  return TEST_FAIL_PATTERN.search(log)

def GetTestState(log):
  if CheckPassed(log):
    return 'PASS'
  elif CheckFailed(log):
    return 'FAIL'
  else:
    return 'ABORT'

def ListAllRuns():
  """List all runs of StressAppTest.

  Searchs for StressAppTest logs in /var/factory/tests. List all of them along
  with their test state.
  """
  ret = []
  for path in glob.glob(LOG_SEARCH_GLOB):
    with open(path, 'r') as f:
      log = f.read()
      ret.append('  {0:<7s}{1:s}'.format(GetTestState(log), path))
  count = len(ret)
  if not ret:
    ret.append('  (none)')
  print 'Found %d runs:\n%s' % (count, '\n'.join(ret))


EXAMPLES = """Examples:

  # Analyze the log from the last run of StressAppTest (only available on DUT)
  bin/memory_error

  # Analyze the log from specific run
  bin/memory_error /var/factory/tests/..../log
"""

def main():
  parser = argparse.ArgumentParser(
      description="Analyze log of StressAppTest.",
      epilog=EXAMPLES,
      formatter_class=argparse.RawDescriptionHelpFormatter)
  parser.add_argument('log_path', metavar='log_path',
                      type=str, help='Path to the log file',
                      default=DEFAULT_LOG_PATH, nargs='?')
  args = parser.parse_args()

  print "Analyzing log: %s" % args.log_path

  error_bit_count = 0
  error_chip_mask = 0

  try:
    with open(args.log_path, 'r') as f:
      log = f.read()
  except IOError:
    print "Cannot open log file %s" % args.log_path
    parser.print_help()
    sys.exit(1)

  if CheckPassed(log):
    print """
    Stress test passed!

    If you have re-run the test after it fails, please specify the
    path to the failed log.
    """
    ListAllRuns()
    sys.exit(0)
  elif not CheckFailed(log):
    print """
    Test aborted!
    Please check if the failure is due to abortion.

    If you have re-run the test after it fails, please specify the
    path to the failed log.
    """
    ListAllRuns()
    sys.exit(1)

  for match in ERROR_PATTERN.finditer(log):
    print match.group(0)
    read_value = int(match.group(1), 16)
    expected_value = int(match.group(3), 16)
    xor_value = read_value ^ expected_value
    error_bit_count += bin(xor_value).count('1')
    error_chip_mask |= GetBadChipMask(xor_value)

  if error_bit_count == 0:
    print """
    No recognizable memory error found.
    Please capture the logs with factory_bug and file an issue.
    """
  elif error_bit_count == 1:
    print "Found single-bit error.  Please re-test."
  else:
    bad_chips = []
    if error_chip_mask & 0x1:
      bad_chips.extend(['U1', 'U6'])
    if error_chip_mask & 0x2:
      bad_chips.extend(['U2', 'U5'])
    if error_chip_mask & 0x4:
      bad_chips.extend(['U3', 'U7'])
    if error_chip_mask & 0x8:
      bad_chips.extend(['U4', 'U8'])
    print """
    Multiple errors found.
    Please replace %s and re-test.
    """ % ','.join(bad_chips)


if __name__ == "__main__":
  main()
