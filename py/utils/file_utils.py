# Copyright (c) 2012 The Chromium OS Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""File-related utilities..."""

import base64
from contextlib import contextmanager
import errno
import fcntl
import fnmatch
import glob
import gzip
import hashlib
import logging
import os
import pipes
import re
import shutil
import stat
import subprocess
import time
import tempfile

import factory_common  # pylint: disable=W0611
from cros.factory.common import CheckDictKeys, MakeList
from cros.factory.test import utils
from cros.factory.tools import mount_partition
from cros.factory.utils import time_utils
from cros.factory.utils.process_utils import Spawn


# This should really be in this module rather than in test.utils.
# TODO: Move TryMakeDirs method to this module and update existing files
# accordingly.
TryMakeDirs = utils.TryMakeDirs


def MakeDirsUidGid(path, uid=-1, gid=-1, mode=0777):
  """Recursive directory creation with specified uid, gid and mode.

  Like os.makedirs, but it also chown() and chmod() to the directories it
  creates.

  Args:
    path: Path to create recursively.
    uid: User id. -1 means unchanged.
    gid: Group id. -1 means unchanged.
    mode: Mode (numeric) of path. Default 0777.
  """
  logging.debug('MakeDirsUidGid %r', path)
  if not path:
    return
  if os.path.isdir(path):
    logging.debug('Path %s exists', path)
    return

  MakeDirsUidGid(os.path.dirname(path), uid, gid, mode)
  os.mkdir(path)
  os.chmod(path, mode)
  os.chown(path, uid, gid)
  logging.debug('mkdir %r with mode 0%o uid %r gid %r', path, mode, uid, gid)


class Glob(object):
  """A glob containing items to include and exclude.

  Properties:
    include: A single pattern identifying files to include.
    exclude: Patterns identifying files to exclude.  This can be
      None, or a single pattern, or a list of patterns.
  """
  def __init__(self, include, exclude=None):
    self.include = include
    if exclude is None:
      self.exclude = []
    elif isinstance(exclude, list):
      self.exclude = exclude
    elif isinstance(exclude, str):
      self.exclude = [exclude]
    else:
      raise TypeError, 'Unexpected exclude type %s' % type(exclude)

  def Match(self, root):
    """Returns files that match include but not exclude.

    Args:
      root: Root within which to evaluate the glob.
    """
    ret = []
    for f in glob.glob(os.path.join(root, self.include)):
      if not any(fnmatch.fnmatch(f, os.path.join(root, pattern))
                 for pattern in self.exclude):
        ret.append(f)
    return ret

  @staticmethod
  def Construct(loader, node):
    """YAML constructor."""
    value = loader.construct_mapping(node)
    CheckDictKeys(value, ['include', 'exclude'])
    return Glob(value['include'], value.get('exclude', None))

  @staticmethod
  def Represent(representer, node):
    """YAML representer."""
    return representer.represent_mapping('!glob', dict(
        include=node.include, exclude=node.exclude))


@contextmanager
def UnopenedTemporaryFile(**kwargs):
  """Yields an unopened temporary file.

  The file is not opened, and it is deleted when the context manager
  is closed if it still exists at that moment.

  Args:
    Any allowable arguments to tempfile.mkstemp (e.g., prefix,
      suffix, dir).
  """
  f, path = tempfile.mkstemp(**kwargs)
  os.close(f)
  try:
    yield path
  finally:
    if os.path.exists(path):
      os.unlink(path)


@contextmanager
def TempDirectory(**kwargs):
  """Yields an temporary directory.

  The temp directory is deleted when the context manager is closed if it still
  exists at that moment.

  Args:
    Any allowable arguments to tempfile.mkdtemp (e.g., prefix,
      suffix, dir).
  """
  path = tempfile.mkdtemp(**kwargs)
  try:
    yield path
  finally:
    if os.path.exists(path):
      shutil.rmtree(path)


def Read(filename):
  """Returns the content of a file.

  It is used to facilitate unittest.

  Args:
    filename: file name.

  Returns:
    File content. None if IOError.
  """
  try:
    with open(filename) as f:
      return f.read()
  except IOError as e:
    logging.error('Cannot read file "%s": %s', filename, e)
    return None


def ReadLines(filename):
  """Returns a file as list of lines.

  It is used to facilitate unittest.

  Args:
    filename: file name.

  Returns:
    List of lines of the file content. None if IOError.
  """
  try:
    with open(filename) as f:
      return f.readlines()
  except IOError as e:
    logging.error('Cannot read file "%s": %s', filename, e)
    return None


def TryUnlink(path):
  """Unlinks a file only if it exists.

  Args:
    path: File to attempt to unlink.

  Raises:
    Any OSError thrown by unlink (except ENOENT, which means that the file
    simply didn't exist).
  """
  try:
    os.unlink(path)
  except OSError as e:
    if e.errno != errno.ENOENT:
      raise


def ReadFile(path):
  """Reads bytes from a file.

  Args:
    path: The path of the file to read.
  """
  with open(path) as f:
    return f.read()


def WriteFile(path, data, log=False):
  """Writes a value to a file.

  Args:
    path: The path to write to.
    data: The value to write.  This may be any type and is stringified with
        str().
    log: Whether to log path and data.
  """
  data = str(data)
  if log:
    logging.info('Writing %r to %s', data, path)
  with open(path, 'w') as f:
    f.write(data)


def PrependFile(path, data, log=False):
  """Prepends a value to a file.

  Note that it is suitable for small file as it reads file content first,
  then writes data and original content back.

  Args:
    path: The path to write to.
    data: The value to write.  This may be any type and is stringified with
        str().
    log: Whether to log path and data.
  """
  data = str(data)
  if log:
    logging.info('Prepend %r to %s', data, path)

  original = None
  if os.path.isfile(path):
    original = Read(path)

  with open(path, 'w') as f:
    f.seek(0)
    f.write(data)
    if original:
      f.write(original)


def TouchFile(path):
  """Touches a file.

  Args:
    path: The path to touch.
  """
  with file(path, 'a'):
    os.utime(path, None)


def SetFileExecutable(path):
  """Sets the file's executable bit.

  Args:
    path: The file path.
  """
  st = os.stat(path)
  os.chmod(path, st.st_mode | stat.S_IXUSR)


def CopyFileSkipBytes(in_file_name, out_file_name, skip_size):
  """Copies a file and skips the first N bytes.

  Args:
    in_file_name: input file_name.
    out_file_name: output file_name.
    skip_size: number of head bytes to skip. Should be smaller than
        in_file size.

  Raises:
    ValueError if skip_size >= input file size.
  """
  in_file_size = os.path.getsize(in_file_name)
  if in_file_size <= skip_size:
    raise ValueError('skip_size: %d should be smaller than input file: %s '
                     '(size: %d)' % (skip_size, in_file_name, in_file_size))

  _CHUNK_SIZE = 4096
  with open(in_file_name, 'rb') as in_file:
    with open(out_file_name, 'wb') as out_file:
      in_file.seek(skip_size)
      shutil.copyfileobj(in_file, out_file, _CHUNK_SIZE)


def Sync(log=True):
  """Calls 'sync'."""
  Spawn(['sync'], log=log, check_call=True)


def ResetCommitTime():
  """Remounts partitions with commit=0.

  The standard value on CrOS (commit=600) is likely to result in
  corruption during factory testing.  Using commit=0 reverts to the
  default value (generally 5 s).
  """
  if utils.in_chroot():
    return

  devices = set()
  with open('/etc/mtab', 'r') as f:
    for line in f.readlines():
      cols = line.split(' ')
      device = cols[0]
      options = cols[3]
      if 'commit=' in options:
        devices.add(device)

  # Remount all devices in parallel, and wait.  Ignore errors.
  for process in [
      Spawn(['mount', p, '-o', 'commit=0,remount'], log=True)
      for p in sorted(devices)]:
    process.wait()


def GetMainStorageDevice():
  """Returns the path to the main storage device."""
  with open('/etc/mtab') as f:
    for line in f.readlines():
      fields = line.split()
      if fields[1] == '/usr/local' and fields[0].startswith('/dev/'):
        device = fields[0]
        # Remove the partition number (including the letter 'p' if any)
        # and return.
        return re.sub(r'p?(\d+)$', '', device)

  raise IOError('Unable to find main storage device in /etc/mtab')


def MountDeviceAndReadFile(device, path):
  """Mounts a device and reads a file on it.

  Args:
    device: The device like '/dev/mmcblk0p5'.
    path: The file path like '/etc/lsb-release'. The file to read is then
      'mount_point/etc/lsb-release'.

  Returns:
    The content of the file.

  Raises:
    Exception if mount or umount fails.
    IOError if the file can not be read.
  """
  # Remove the starting / of the path.
  path = re.sub('^/', '', path)
  with mount_partition.MountPartition(device) as mount_point:
    logging.debug('Mounted at %s.', mount_point)
    content = open(
        os.path.join(mount_point, path)).read()
  return content


@contextmanager
def GunzipSingleFile(gzip_path, output_path=None):
  """Extracts a gzip file which contains only one file.

  Args:
    gzip_path: Path to gzipped file.
    output_path: Path to extract. None to use a temporary output file.

  Yields:
    Path to extracted file. If output_path is omitted, yields a temporary file
    path. Note that it deletes the temporary file after leaving the context.
  """
  MAX_CHUNK_SIZE = 10 * 1024 * 1024

  is_temp_file = not output_path
  if not output_path:
    f, output_path = tempfile.mkstemp()
    os.close(f)

  with open(output_path, 'w') as output_file:
    with gzip.open(gzip_path, 'rb') as input_file:
      while True:
        chunk = input_file.read(MAX_CHUNK_SIZE)
        if not chunk:
          break
        output_file.write(chunk)

  try:
    yield output_path
  finally:
    if is_temp_file and os.path.exists(output_path):
      os.unlink(output_path)


class ExtractFileError(Exception):
  """Failure of extracting compressed file."""
  pass


def ExtractFile(compressed_file, output_dir, only_extracts=None,
                overwrite=True, quiet=False):
  """Extracts compressed file to output folder.

  Args:
    compressed_file: Path to a compressed file.
    output_dir: The path to the output directory.
    only_extracts: An optional list of files to extract from the given
      compressed file.
    overwrite: Whether to overwrite existing files without prompt.  Defaults to
      True.
    quiet: Whether to suppress output.

  Raises:
    ExtractFileError if the method fails to extract the file.
  """
  TryMakeDirs(output_dir)
  logging.info('Extracting %s to %s', compressed_file, output_dir)
  only_extracts = MakeList(only_extracts) if only_extracts else []
  if only_extracts:
    logging.info('Extracts only file(s): %s', only_extracts)

  if compressed_file.endswith('.zip'):
    overwrite_opt = ['-o'] if overwrite else []
    quiet_opt = ['-qq'] if quiet else []
    cmd = (['unzip'] + overwrite_opt + quiet_opt + [compressed_file] +
           ['-d', output_dir] +
           only_extracts)
  elif (any(compressed_file.endswith(suffix) for suffix in
            ('.tar.bz2', '.tbz2', '.tar.gz', '.tgz', 'tar.xz', '.txz'))):
    overwrite_opt = [] if overwrite else ['--keep-old-files']
    verbose_opt = [] if quiet else ['-vv']
    cmd = (['tar', '-xf'] +
           overwrite_opt + [compressed_file] + verbose_opt +
           ['-C', output_dir] + only_extracts)
  else:
    raise ExtractFileError('Unsupported compressed file: %s' % compressed_file)

  return Spawn(cmd, log=True, check_call=True)


def ForceSymlink(target, link_name):
  """Makes a symlink to target even if link_name already exists.

  Args:
    target: target file path
    link_name: symlink name.

  Raises:
    Exception: target is missing
    OSError: failed to make symlink
  """
  if not os.path.exists(target):
    raise Exception('Missing symlink target: ' + target)
  TryUnlink(link_name)
  os.symlink(target, link_name)


def CheckPath(path, description=None):
  """Checks if the path exists.

  It raises IOError with default message "No such file or directory" if
  path not found. If file_type is given, the error message becomes:
  "Missing file_type".

  Args:
    path: path to check
    description: the description of the path to check, e.g. "factory bundle".

  Raises:
    IOError
  """
  if not os.path.exists(path):
    message = ('Missing ' + description if description else
               'No such file or directory')
    raise IOError(errno.ENOENT, message, path)


def AtomicCopy(source, dest):
  """Copies source file to dest in an atomic manner.

  It copies source to a temporary file first. Then renames the temp file to
  dest. It avoids interrupting others reading the dest file while copying.

  Args:
    source: source filename
    dest: destination filename
  """
  CheckPath(source, description='source')
  with UnopenedTemporaryFile() as temp_path:
    shutil.copy2(source, temp_path)
    os.rename(temp_path, dest)


def Md5sumInHex(filename):
  """Gets hex coded md5sum of input file."""
  # pylint: disable=E1101
  return hashlib.md5(
      open(filename, 'rb').read()).hexdigest()


def B64Sha1(filename):
  """Gets standard base64 coded sha1 sum of input file."""
  # pylint: disable=E1101
  return base64.standard_b64encode(hashlib.sha1(
      open(filename, 'rb').read()).digest())


class FileLockTimeoutError(Exception):
  """Timeout error for FileLock."""
  pass


class FileLock(object):
  """An exclusive lock implemented with file lock.

  The lock is designed to work either in one process or across multiple
  processes. Call Acquire() to acquire the file lock. The file lock is release
  either by calling Release() manually, or when the process is terminated.

  Args:
    lockfile: The path to the file used as lock.
    timeout_secs: The maximum duration in seconds to wait for the lock, or None
      to fail immediately if unable to acquire lock.
  """
  def __init__(self, lockfile, timeout_secs=None):
    self._lockfile = lockfile
    self._timeout_secs = timeout_secs
    self._fd = os.open(lockfile, os.O_RDWR | os.O_CREAT)
    self._locked = False

  def Acquire(self):
    if self._timeout_secs:
      end_time = time_utils.MonotonicTime() + self._timeout_secs

    while True:
      try:
        fcntl.flock(self._fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        self._locked = True
        logging.debug('%s locked by %s', self._lockfile, os.getpid())
        break
      except IOError:
        if self._timeout_secs:
          time.sleep(0.1)
          if time_utils.MonotonicTime() > end_time:
            raise FileLockTimeoutError(
                'Could not acquire file lock of %s in %s second(s)' %
                (self._lockfile, self._timeout_secs))
        else:
          raise

  def Release(self):
    if self._locked:
      fcntl.flock(self._fd, fcntl.LOCK_UN)
      self._locked = False
      logging.debug('%s unlocked by %s', self._lockfile, os.getpid())

  def __enter__(self):
    return self.Acquire()

  def __exit__(self, *args, **kwargs):
    self.Release()


def WriteWithSudo(file_path, content):
  """Writes content to file_path with sudo=True.

  Args:
    file_path: The path to write to.
    content: The content to write.
  """
  # Write with sudo, since only root can write this.
  process = Spawn(
      'cat > %s' % pipes.quote(file_path), sudo=True,
      stdin=subprocess.PIPE, shell=True)
  process.stdin.write(content)
  process.stdin.close()
  if process.wait():
    raise subprocess.CalledProcessError('Unable to write %s' % file_path)


def GlobSingleFile(pattern):
  """Returns the name of the single file matching a pattern.

  Args:
    pattern: A pattern that should match exactly one file.

  Raises:
    ValueError if the pattern matches zero or >1 files.
  """
  matches = glob.glob(pattern)
  if len(matches) != 1:
    raise ValueError, 'Expected one match for %s but got %s' % (
        pattern, matches)

  return matches[0]
