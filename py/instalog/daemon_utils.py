# Copyright 2016 The Chromium OS Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Daemon-related utilities."""

# TODO(kitching): Moving this to the cros.factory.utils directory once
#                 feature-complete.  We may want to convert gooftools/wipe.py
#                 to use it.
# TODO(kitching): Write unittests for this module.

from __future__ import print_function

import atexit
import os
import signal
import sys
import time


CHILD = 0
PARENT = 1


class Daemon(object):
  """A generic daemon class.

  Usage: subclass the Daemon class and override the run() method.

  Based on Sander Marechal's public domain code sample: http://goo.gl/9tMDrh
  """

  def __init__(self, pidfile, stdin='/dev/null', stdout='/dev/null',
               stderr='/dev/null'):
    self.stdin = stdin
    self.stdout = stdout
    self.stderr = stderr
    self.pidfile = pidfile

  def _Daemonize(self):
    """Daemonizes the daemon with a UNIX double-fork.

    Do the UNIX double-fork magic.  See Stevens' "Advanced
    Programming in the UNIX Environment" for details (ISBN 0201563177)
    http://www.erlenstar.demon.co.uk/unix/faq_2.html#SEC16
    """
    try:
      pid = os.fork()
      if pid > 0:
        # Exit first parent.
        return PARENT
    except OSError as e:
      sys.stderr.write('fork #1 failed: %d (%s)\n' % (e.errno, e.strerror))
      sys.exit(1)

    # Decouple from parent environment.
    os.chdir('/')
    os.setsid()
    os.umask(0)

    # Do second fork.
    try:
      pid = os.fork()
      if pid > 0:
        # Exit from second parent.
        sys.exit(0)
    except OSError as e:
      sys.stderr.write('fork #2 failed: %d (%s)\n' % (e.errno, e.strerror))
      sys.exit(1)

    # Redirect standard file descriptors.
    sys.stdout.flush()
    sys.stderr.flush()
    si = file(self.stdin, 'r')
    so = file(self.stdout, 'a+')
    se = file(self.stderr, 'a+', 0)
    os.dup2(si.fileno(), sys.stdin.fileno())
    os.dup2(so.fileno(), sys.stdout.fileno())
    os.dup2(se.fileno(), sys.stderr.fileno())

    # Remove pidfile when exiting.
    atexit.register(self._RemovePID)

    # Write pidfile.
    self._WritePID()

  def _WritePID(self):
    """Writes the current process's PID to the pidfile."""
    pid = str(os.getpid())
    file(self.pidfile, 'w+').write('%s\n' % pid)

  def _RemovePID(self):
    """Unlinks the pidfile."""
    os.remove(self.pidfile)

  def GetPID(self):
    """Returns the current PID of the daemon process, or None if not found."""
    try:
      with open(self.pidfile, 'r') as f:
        return int(f.read().strip())
    except IOError:
      return None

  def IsRunning(self):
    """Checks that the service is running."""
    pid = self.GetPID()
    if not pid:
      return False
    try:
      os.kill(pid, 0)
    except OSError:
      return False
    return True

  def IsStopped(self):
    """Checks that the service is stopped."""
    return not self.IsRunning()

  def Start(self, foreground=False):
    """Starts the daemon."""
    # Check for a pidfile to see if the daemon is already running.
    if self.GetPID() and self.IsStopped():
      # Not sure if this is the safest thing to do...
      message = 'pidfile %s exists, but pid is down. Removing pidfile\n'
      sys.stderr.write(message % self.pidfile)
      os.remove(self.pidfile)
    elif self.IsRunning():
      message = 'pidfile %s already exists, and pid is running\n'
      sys.stderr.write(message % self.pidfile)
      sys.exit(1)

    # Start the daemon.
    if not foreground:
      if self._Daemonize() == PARENT:
        return
    self.Run(foreground)

  def Stop(self):
    """Stops the daemon."""
    pid = self.GetPID()

    if not pid:
      message = 'pidfile %s does not exist. Daemon not running?\n'
      sys.stderr.write(message % self.pidfile)
      return  # Not an error in a restart.

    # Try killing the daemon process.
    try:
      while True:
        os.kill(pid, signal.SIGTERM)
        time.sleep(0.1)
    except OSError as err:
      if 'No such process' in str(err):
        if os.path.exists(self.pidfile):
          os.remove(self.pidfile)
      else:
        print(str(err))
        sys.exit(1)

  def Status(self):
    """Prints the status of the daemon."""
    pid = self.GetPID()

    if not pid:
      message = 'pidfile %s does not exist. Daemon not running?\n'
      sys.stderr.write(message % self.pidfile)
      return

    print('Running at PID %d' % pid)


  def Restart(self):
    """Restarts the daemon."""
    self.Stop()
    self.Start()

  def Run(self, foreground):
    """Runs the code that represents the daemon process.

    Override this method when subclasssing Daemon. It will be called
    after the process has been daemonized by Start() or Restart().

    It is expected that Run will not necessarily return (daemon main loop
    may be contained in its thread).
    """
    raise NotImplementedError
