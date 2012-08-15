#!/usr/bin/env python
#
# Copyright (c) 2012 The Chromium OS Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

'''Runs a program with LOCK_FILE locked exclusively.

Symlink an executable name to this script.  This script will
find that executable, lock LOCK_FILE, run the executable as a
subprocess, and return its exit code.
'''

import fcntl
import os
import sys

LOCK_FILE = '/tmp/ec_lock'

def main():
  fd = os.open(LOCK_FILE, os.O_WRONLY | os.O_CREAT)
  fcntl.flock(fd, fcntl.LOCK_EX)

  my_path = os.path.realpath(__file__)
  my_name = os.path.basename(sys.argv[0])

  os.environ['PATH'] = ':'.join([
      x for x in os.environ['PATH'].split(':')
      if not os.path.exists(os.path.join(x, 'ec_lock'))])

  if my_name == 'ec_lock':
    os.execvp(sys.argv[1], sys.argv[1:])
    print >> sys.stderr, 'Unable to exec %s' % sys.argv[1]
    sys.exit(1)

  for d in os.environ['PATH'].split(':'):
    f = os.path.join(d, my_name)
    if os.path.exists(f) and os.path.realpath(f) != my_path:
      os.execv(f, sys.argv)
      print >> sys.stderr, 'Unable to exec %s' % f
      sys.exit(1)

  print >> sys.stderr, 'Unable to find %s in $PATH' % my_name
  sys.exit(1)

if __name__ == '__main__':
  main()
