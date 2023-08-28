#!/usr/bin/env python3
#
# Copyright 2012 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.
"""Runs unittests in parallel."""

import argparse
import contextlib
import datetime
import glob
import logging
import multiprocessing
import os
import random
import re
import shutil
import signal
import socketserver
import struct
import subprocess
from subprocess import STDOUT
import sys
import tempfile
import threading
import time
from typing import Collection, Generator, MutableMapping, Optional, Sequence, Set, Tuple, cast

from cros.factory.tools.unittest_tools import mock_loader
from cros.factory.unittest_utils import label_utils
from cros.factory.utils.debug_utils import SetupLogging
from cros.factory.utils import file_utils
from cros.factory.utils import net_utils
from cros.factory.utils import process_utils


FACTORY_ROOT = os.path.abspath(
    os.path.join(os.path.dirname(os.path.realpath(__file__)), '..', '..'))
# Directories to search unit test files starting from factory repository root.
DIRECTORIES_TO_SEARCH = [
    'py',
    'po',
    'go',
]
# Tests exclude starting from factory repository root. Content can be either
# directory or filename.
TESTS_TO_EXCLUDE = [
    'py/bundle_creator',
    'py/probe_info_service',
    'py/dome',
    'py/umpire',
    # TODO (b/204134192)
    'py/test/utils/media_utils_unittest.py',
    'py/test_list_editor',
]
# TEST_PASSED_MARK is the .tests-passed file at factory root path
TEST_PASSED_MARK = os.path.join(FACTORY_ROOT, '.tests-passed')
# Timeout for running any individual test program.
TEST_DEFAULT_TIMEOUT_SECS = 60
TEST_FILE_SUFFIX = '_unittest.py'
TEST_FILE_USE_MOCK_SUFFIX = '_unittest_mocked.py'


class _TestProc:
  """Creates and runs a subprocess to run an unittest.

  Besides creating a subprocess, it also prepares a temp directory for
  env CROS_FACTORY_DATA_DIR, records a test start time and test path.

  The temp directory will be removed once the object is destroyed.

  Args:
    test_name: unittest path.
    log_name: path of log file for unittest.
    port_server: port server used by net_utils
    python_path: factory module path to be imported in process
    timeout: timeout per test in seconds
  """

  def __init__(self, test_name: str, log_name: str, port_server: str,
               python_path: str, timeout: int, coverage: bool):
    self.test_name = test_name
    self.log_file_name = log_name
    self._port_server = port_server
    self._python_path = python_path
    self._timeout = timeout
    self._cros_factory_data_dir = cast(str, None)
    self.start_time = cast(float, None)
    self.proc = cast(process_utils.ExtendedPopen, None)
    self.coverage = coverage

  def __enter__(self):
    self._cros_factory_data_dir = tempfile.mkdtemp(
        prefix='cros_factory_data_dir.')
    child_tmp_root = os.path.join(self._cros_factory_data_dir, 'tmp')
    os.mkdir(child_tmp_root)

    child_env = os.environ.copy()
    child_env['PYTHONPATH'] = self._python_path
    child_env['CROS_FACTORY_DATA_DIR'] = self._cros_factory_data_dir
    # Since some tests using `make par` is sensitive to file changes inside py
    # directory, don't generate .pyc file.
    child_env['PYTHONDONTWRITEBYTECODE'] = '1'
    # Unittests should not be run with user-specific site-pacakges.
    child_env['PYTHONNOUSERSITE'] = '1'
    # Change child calls for tempfile.* to be rooted at directory inside
    # cros_factory_data_dir temporary directory, so it would be removed even if
    # the test is terminated.
    child_env['TMPDIR'] = child_tmp_root
    child_env['PYTHONWARNINGS'] = 'error::ResourceWarning'
    # This is used by net_utils.FindUnusedPort, to eliminate the chance of
    # collision of FindUnusedPort between different unittests.
    child_env[
        'CROS_FACTORY_UNITTEST_PORT_DISTRIBUTE_SERVER'] = self._port_server
    with open(self.log_file_name, 'w', encoding='utf8') as log_file:
      self.start_time = time.time()
      if self.coverage:
        self.proc = process_utils.Spawn(['coverage', 'run', self.test_name],
                                        stdout=log_file, stderr=STDOUT,
                                        env=child_env)
      else:
        self.proc = process_utils.Spawn([self.test_name], stdout=log_file,
                                        stderr=STDOUT, env=child_env)

    process_utils.StartDaemonThread(target=self._WatchTest)
    return self

  def __exit__(self, exc_type, exc_value, traceback):
    if os.path.isdir(self._cros_factory_data_dir):
      shutil.rmtree(self._cros_factory_data_dir)
    self._ForceKillProcess()

  def _WatchTest(self):
    """Watches a test, killing it if it times out."""
    try:
      self.proc.wait(self._timeout)
    except subprocess.TimeoutExpired:
      logging.error('Test %s still alive after %d secs: killing it',
                    self.test_name, self._timeout)
      self.proc.send_signal(signal.SIGINT)
      time.sleep(1)
      self._ForceKillProcess()

  def _ForceKillProcess(self):
    """Force kill process without raising any attention."""
    self.proc.kill()
    self.proc.wait()


class PortDistributeHandler(socketserver.StreamRequestHandler):

  def handle(self):
    length = struct.unpack('B', self.rfile.read(1))[0]
    assert isinstance(self.server, PortDistributeServer)
    port = self.server.RequestPort(length)
    self.wfile.write(struct.pack('<H', port))


class PortDistributeServer(socketserver.ThreadingUnixStreamServer):

  def __init__(self, socket_file: str):
    super().__init__(socket_file, PortDistributeHandler)
    self.lock = threading.RLock()
    self.unused_ports = set(
        range(net_utils.UNUSED_PORT_LOW, net_utils.UNUSED_PORT_HIGH))
    self.thread = cast(threading.Thread, None)

  def __enter__(self):
    self.thread = threading.Thread(target=self.serve_forever)
    self.thread.start()

  def __exit__(self, *args):
    self.server_close()
    if self.thread:
      net_utils.ShutdownTCPServer(self)
      self.thread.join()

  def RequestPort(self, length: int) -> int:
    with self.lock:
      while True:
        port = random.randint(net_utils.UNUSED_PORT_LOW,
                              net_utils.UNUSED_PORT_HIGH - length)
        port_range = set(range(port, port + length))
        if self.unused_ports.issuperset(port_range):
          self.unused_ports.difference_update(port_range)
          break
      return port


@contextlib.contextmanager
def CreatePortDistributeServer() -> Generator[str, None, None]:
  # Set the temp dir to /tmp to prevent the socket path longer than 108
  # characters (the unix socket file name length limit in linux).
  with tempfile.TemporaryDirectory(dir='/tmp') as temp_dir:
    socket_file = os.path.join(temp_dir, 'sock')
    with PortDistributeServer(socket_file):
      yield socket_file


class RunTests:
  """Runs unittests in parallel.

  Args:
    tests: list of unittest paths.
    max_jobs: maxinum number of parallel tests to run.
    log_dir: base directory to store test logs.
    plain_log: disable color and progress in log.
    timeout: timeout per test in seconds.
    isolated_tests: list of test to run in isolate mode.
    fallback: True to re-run failed test sequentially.
  """

  def __init__(
      self,
      tests: Collection[str],
      max_jobs: int,
      log_dir: str,
      plain_log: bool,
      timeout: int,
      isolated_tests: Optional[Sequence[str]] = None,
      fallback: bool = True,
      coverage: bool = False,
  ):
    self._tests = tests
    self._max_jobs = max_jobs
    self._log_dir = log_dir
    self._plain_log = plain_log
    self._timeout = timeout
    self._isolated_tests = isolated_tests if isolated_tests else []
    self._fallback = fallback
    self._start_time = time.time()
    self.coverage = coverage

    # A dict to store running subprocesses. pid: (_TestProc, test_name).
    self._running_proc: MutableMapping[int, Tuple[_TestProc, str]] = {}
    self._abort_event = threading.Event()

    # set of passed test_name
    self._passed_tests: Set[str] = set()
    # dict of failed test name -> log file
    self._failed_tests: MutableMapping[str, str] = {}
    # dict of test name -> number of runs so far
    self._run_counts: MutableMapping[str, int] = {}

    def AbortHandler(sig, frame):
      del sig, frame  # Unused.
      if not self._abort_event.isSet():
        print('\033[1;33mGot ctrl-c, gracefully shutdown.\033[22;0m')
      else:
        print('\033[1;33mTerminating runner and all subprocess...\033[22;0m')
      self._abort_event.set()

    signal.signal(signal.SIGINT, AbortHandler)

  def Run(self) -> int:
    """Runs all unittests.

    Returns:
      0 if all passed; otherwise, 1.
    """
    if self._max_jobs > 1:
      tests = set(self._tests) - set(self._isolated_tests)
      num_total_tests = len(tests) + len(self._isolated_tests)
      self._InfoMessage(
          f'Run {len(tests)} tests in parallel with {int(self._max_jobs)} jobs:'
      )
    else:
      tests = set(self._tests) | set(self._isolated_tests)
      num_total_tests = len(tests)
      self._InfoMessage(f'Run {len(tests)} tests sequentially:')

    self._RunInParallel(tests, self._max_jobs)
    if self._max_jobs > 1 and self._isolated_tests:
      self._InfoMessage(
          f'Run {len(self._isolated_tests)} isolated tests sequentially:')
      self._RunInParallel(self._isolated_tests, 1)

    self._PassMessage(
        f'{len(self._passed_tests)}/{int(num_total_tests)} tests passed.')

    if self._failed_tests and self._fallback:
      self._InfoMessage('Re-run failed tests sequentially:')
      rerun_tests = sorted(self._failed_tests.keys())
      self._failed_tests.clear()
      self._RunInParallel(rerun_tests, 1)
      self._PassMessage(
          f'{len(self._passed_tests)}/{len(self._tests)} tests passed.')

    self._InfoMessage(f'Elapsed time: {time.time() - self._start_time:.2f} s')

    if self._failed_tests:
      self._FailMessage(f'Logs of {len(self._failed_tests)} failed tests:')
      # Log all the values in the dict (i.e., the log file paths)
      for test_name, log_path in sorted(self._failed_tests.items()):
        self._FailMessage(f'{log_path} ({test_name}):\n'
                          f'{file_utils.ReadFile(log_path)}')
      return 1
    return 0

  def _GetLogFilename(self, test_path: str) -> str:
    """Composes log filename.

    Log filename is based on unittest path.  We replace '/' with '_' and
    add the run number (1-relative).

    Args:
      test_path: unittest path.

    Returns:
      log filename (with path) for the test.
    """
    if test_path.find('./') == 0:
      test_path = test_path[2:]

    run_count = self._run_counts[test_path] = self._run_counts.get(
        test_path, 0) + 1

    return os.path.join(self._log_dir,
                        f"{test_path.replace('/', '_')}.{int(run_count)}.log")

  def _RunInParallel(self, tests: Collection[str], max_jobs: int):
    """Runs tests in parallel.

    It creates subprocesses and runs in parallel for at most max_jobs.
    It is blocked until all tests are done.

    Args:
      tests: list of unittest paths.
      max_jobs: maximum number of tests to run in parallel.
    """
    with CreatePortDistributeServer() as port_server_socket_file, \
         mock_loader.Loader(TESTS_TO_EXCLUDE) as loader, \
         contextlib.ExitStack() as stack:
      for test_name in tests:
        python_path = loader.GetMockedRoot() if test_name.endswith(
            TEST_FILE_USE_MOCK_SUFFIX) else os.getenv('PYTHONPATH', '')
        try:
          p = stack.enter_context(
              _TestProc(test_name, self._GetLogFilename(test_name),
                        port_server_socket_file, python_path, self._timeout,
                        self.coverage))
        except Exception:
          self._FailMessage(f'Error running test {test_name!r}')
          raise
        self._running_proc[p.proc.pid] = (p, os.path.basename(test_name))
        self._WaitRunningProcessesFewerThan(max_jobs)
      # Wait for all running test.
      self._WaitRunningProcessesFewerThan(1)

  def _CheckTestFailedReason(self, p: _TestProc) -> Optional[str]:
    """Returns fail reason or None if test passed.

    Not only checks the return code of the test process, but also examines is
    any ResourceWarning presents in the test log.

    Args:
      p: _TestProc instance

    Returns:
      A string of failed message or None if test passed.
    """
    if p.proc.returncode != 0:
      return f'return code is not 0 (return:{p.proc.returncode})'

    # Due to resourceWarning such as file not closed can only be determined
    # when GC is going to delete that object, CPython can not throw exception
    # at that time to mark test is failed, we have to manually check the log.
    if re.search(r'Exception ignored in: .*\nResourceWarning: .*',
                 file_utils.ReadFile(p.log_file_name)):
      return 'ResourceWarning found'

    return None

  def _RecordTestResult(self, p: _TestProc):
    """Records test result.

    Places the completed test to either success or failure list based on
    its returncode. Also print out PASS/FAIL message with elapsed time.

    Args:
      p: _TestProc object.
    """
    duration = time.time() - p.start_time
    failedReason = self._CheckTestFailedReason(p)
    if failedReason:
      self._FailMessage(
          f'*** FAIL [{duration:.2f} s] {p.test_name} ({failedReason})')
      self._failed_tests[p.test_name] = p.log_file_name
    else:
      self._PassMessage(f'*** PASS [{duration:.2f} s] {p.test_name}')
      self._passed_tests.add(p.test_name)

  def _TerminateAndCleanupAll(self):
    """Terminate all running process and cleanup temporary directories.

    Doing terminate gracefully by sending SIGINT to all process first, wait for
    1 second, and then raise interrupt to force leave. The cleanup of all
    process are handled by the context manager.
    """
    for test_proc, unused_name in self._running_proc.values():
      test_proc.proc.send_signal(signal.SIGINT)
    time.sleep(1)
    raise KeyboardInterrupt

  def _WaitRunningProcessesFewerThan(self, threshold: int):
    """Waits until #running processes is fewer than specifed.

    It is a blocking call. If #running processes >= thresold, it waits for a
    completion of a child.

    Args:
      threshold: if #running process is fewer than this, the call returns.
    """
    self._ShowRunningTest()
    while len(self._running_proc) >= threshold:
      if self._abort_event.isSet():
        # Ctrl-c got, cleanup and exit.
        self._TerminateAndCleanupAll()

      terminated_procs = [
          test_proc for test_proc, unused_name in self._running_proc.values()
          if test_proc.proc.returncode is not None
      ]
      for test_proc in terminated_procs:
        del self._running_proc[test_proc.proc.pid]
        self._RecordTestResult(test_proc)
        self._ShowRunningTest()
      self._abort_event.wait(0.05)

  def _PassMessage(self, message: str):
    self._ClearLine()
    print(message if self._plain_log else f'\033[22;32m{message}\033[22;0m')

  def _FailMessage(self, message: str):
    self._ClearLine()
    print(message if self._plain_log else f'\033[22;31m{message}\033[22;0m')

  def _InfoMessage(self, message: str):
    self._ClearLine()
    print(message)

  def _ClearLine(self):
    if not self._plain_log:
      sys.stderr.write('\r\033[K')

  def _ShowRunningTest(self):
    if not self._running_proc or self._plain_log:
      return
    status = f'-> {len(self._running_proc)} tests running'
    running_tests = ', '.join([p[1] for p in self._running_proc.values()])
    if len(status) + 3 + len(running_tests) > 80:
      running_tests = running_tests[:80 - len(status) - 6] + '...'
    self._ClearLine()
    sys.stderr.write(f'{status} [{running_tests}]')
    sys.stderr.flush()


def FindTests(directory: str) -> Set[str]:
  """Returns a set of test filenames starting from the given directory.

  filenames ending with TEST_FILE_SUFFIX or TEST_FILE_USE_MOCK_SUFFIX are
  treated as test.
  """
  return set(glob.glob(
      f'{directory}/**/*{TEST_FILE_SUFFIX}', recursive=True)) | set(
          glob.glob(f'{directory}/**/*{TEST_FILE_USE_MOCK_SUFFIX}',
                    recursive=True))


def GetUnitTestFilenames() -> Sequence[str]:
  """Searches and returns list of test filenames starting from factory root."""
  test_files = set()
  for d in DIRECTORIES_TO_SEARCH:
    test_files |= FindTests(os.path.join(FACTORY_ROOT, d))

  for item in TESTS_TO_EXCLUDE:
    full_path = os.path.join(FACTORY_ROOT, item)
    if os.path.isdir(full_path):
      test_files -= FindTests(full_path)
    else:
      test_files.remove(full_path)

  return [os.path.relpath(p, FACTORY_ROOT) for p in test_files]


def main():
  parser = argparse.ArgumentParser(description='Runs unittests in parallel.')
  parser.add_argument('--jobs', '-j', type=int,
                      default=multiprocessing.cpu_count(),
                      help='Maximum number of tests to run in parallel.')
  parser.add_argument(
      '--log-dir', '-l', default=os.path.join(
          tempfile.gettempdir(),
          'test.logs.' + datetime.datetime.now().strftime('%Y%m%d_%H%M%S')),
      help='directory to place logs.')
  parser.add_argument('--isolated', '-i', nargs='*', default=[],
                      help='Isolated unittests which run sequentially.')
  parser.add_argument('--nofallback', action='store_true',
                      help='Do not re-run failed test sequentially.')
  parser.add_argument('--no-informational', action='store_false',
                      dest='informational',
                      help='Do not run informational tests.')
  parser.add_argument('--no-pass-mark', action='store_false', dest='pass_mark',
                      help='Neither output nor update test pass mark file.')
  parser.add_argument('--plain-log', action='store_true',
                      help='disable color and progress in log.')
  parser.add_argument('--timeout', default=TEST_DEFAULT_TIMEOUT_SECS, type=int,
                      help='The timeout for each test.')
  parser.add_argument('--coverage', action='store_true',
                      help='Calculate coverage when running tests.')
  parser.add_argument('test', nargs='*', help='Unittest filename.')
  args = parser.parse_args()

  SetupLogging()

  # If not run all test, pass mark should be false
  if args.test or not args.informational:
    args.pass_mark = False

  args.test = args.test if args.test else GetUnitTestFilenames()

  os.makedirs(args.log_dir, exist_ok=True)

  label_utils.SetSkipInformational(not args.informational)

  runner = RunTests(args.test, args.jobs, args.log_dir, args.plain_log,
                    args.timeout, isolated_tests=args.isolated,
                    fallback=not args.nofallback, coverage=args.coverage)
  return_value = runner.Run()
  if return_value == 0 and args.pass_mark:
    with open(TEST_PASSED_MARK, 'a', encoding='utf8'):
      os.utime(TEST_PASSED_MARK, None)
  sys.exit(return_value)


if __name__ == '__main__':
  main()
