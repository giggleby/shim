#!/usr/bin/env python3
#
# Copyright 2023 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.
"""
'upload_reports_sftp' is a template Python3 script to compress Factory Reports,
upload Report Archives and check file integrity.
"""

import abc
import argparse
import base64
import datetime
import enum
import hashlib
import logging
import os
import re
import shutil
import subprocess
import tarfile
import tempfile
import time
from typing import List, Optional, Tuple, Union

# Constants
DEFAULT_LOG_PATH = 'upload_reports_sftp'
LOG_FORMAT = '%(asctime)s [%(levelname)s] [%(name)s] %(message)s'


class Status(enum.Enum):
  NO_FILE = None
  SUCCESS = True
  FAIL = False


def InitLogging(log_file: str):
  file_handler = logging.FileHandler(log_file)
  file_handler.setFormatter(logging.Formatter(LOG_FORMAT))
  stream_handler = logging.StreamHandler()
  stream_handler.setFormatter(logging.Formatter(LOG_FORMAT))
  logger = logging.getLogger()
  logger.setLevel(logging.INFO)
  logger.handlers = [file_handler, stream_handler]
  logging.info('Initialized logging system')


def ParseArgument():
  """Parses arguments from the user."""
  parser = argparse.ArgumentParser(
      formatter_class=argparse.RawDescriptionHelpFormatter,
      description='Upload Factory Reports to Google SFTP server script')
  parser.add_argument(
      'factory_report_dir', help='The path of Factory Report directory.  '
      'Example: /cros_docker/umpire/<Dome project name>/umpire_data/report')
  parser.add_argument('hostname', help='The SFTP server hostname.')
  parser.add_argument('port', help='The port for the SFTP server.')
  parser.add_argument('account', help='The SFTP server account.  '
                      'Example: cpfe-<ODM>')
  parser.add_argument(
      'key_path',
      help='The path to the private key of the SFTP server account.  '
      'Example: /home/.ssh/sftp_key')
  parser.add_argument(
      '--target_dir',
      help='The path for the uploaded archives on SFTP server.  The path have '
      'to be existed before using this script.  Default is '
      'None and it represents root path.  Example: /<project name>',
      default='.')
  parser.add_argument(
      '--log_dir', '-l',
      help='The path to the log directory which will save archives, logs and '
      f'metadata.  Default: {DEFAULT_LOG_PATH}', default=DEFAULT_LOG_PATH)
  parser.add_argument(
      '--no_hash_check', dest='hash_check', action='store_false',
      help='To reduce network usage or speed up the process, do not download '
      'uploaded files and check the hash value')
  return parser.parse_args()


def TryMakeDirs(path: str):
  os.makedirs(path, exist_ok=True)


class ReportFinder:
  DATE_FORMAT = '%Y%m%d'

  def __init__(self, factory_report_dir: str):
    self.factory_report_dir = factory_report_dir

  def FindOneReportDir(self) -> Optional[str]:
    """Detects valid and readied daily reports from the report directory.

    When there are multiple valid daily report directories, only the first one
    is returned.

    Returns:
      The path to the valid directory with Factory Reports.  If there's no valid
      path, return None.
    """
    dirs = os.listdir(self.factory_report_dir)
    dirs.sort()
    for daily_report_dir in dirs:
      if self._IsValidReportDir(daily_report_dir):
        return os.path.join(self.factory_report_dir, daily_report_dir)
    return None

  def _IsValidReportDir(self, daily_report_dir: str) -> bool:
    """Checks if the daily report directory is valid and ready to process.

    The report directory which is created by umpire should follow the format
    'YYYYmmdd'.  A report directory is ready if it is created at least 2 days
    prior to the current date.
    """
    if not len(daily_report_dir) == 8:
      return False
    try:
      date = datetime.datetime.strptime(daily_report_dir,
                                        self.DATE_FORMAT).date()
    except ValueError:
      return False
    return date <= datetime.date.today() - datetime.timedelta(days=2)


class ReportArchiver:
  ARCHIVE_SIZE_THRESHOLD = 2 * 1024 * 1024 * 1024  # 2GB

  def __init__(self, report_finder: ReportFinder, archive_dir: str,
               finished_report_dir: str):
    self.report_finder = report_finder
    self.archive_dir = archive_dir
    self.finished_report_dir = finished_report_dir
    logging.info('Initialized ReportArchiver')

  def ProduceArchives(self) -> Status:
    """Detects valid report directory and archives it.

    This function creates a list of archives for just one day (one directory).
    If an archive is larger than ARCHIVE_SIZE_THRESHOLD, it will produce another
    archive for the remaining files in the directory.

    Returns:
      Status Enum.
    """
    report_dir_found = self.report_finder.FindOneReportDir()
    if not report_dir_found:
      return Status.NO_FILE
    logging.info('Found valid report directory %s', report_dir_found)
    if self._ArchiveAll(report_dir_found):
      self._CleanUp(report_dir_found)
      return Status.SUCCESS
    return Status.FAIL

  def _ArchiveAll(self, dir_to_archive: str) -> bool:
    """Archives a directory to archives and checks their file integrity.

    If the directory is empty, it will not produce any archive. If the directory
    has many reports, it may produce two or more archives.

    Returns:
      True if it archives a directory correctly; otherwise, return False.
    """
    archived_list = []
    index = 0
    report_day = os.path.basename(dir_to_archive)

    while True:
      archive_path = os.path.join(self.archive_dir, f'{report_day}-{index}.tar')
      tmp_path = f'{archive_path}.tmp'
      files_added = self._ArchiveOne(dir_to_archive, tmp_path, archived_list)
      if files_added is None:
        os.unlink(tmp_path)
        logging.error('Failed to archive %s', dir_to_archive)
        return False
      if not files_added:
        os.unlink(tmp_path)
        logging.info('Produced %d archives successfully from %s', index,
                     dir_to_archive)
        return True
      # Atomic function if the source and the destination file are on the same
      # file system.
      shutil.move(tmp_path, archive_path)
      logging.info('Produced an archive %s with %d factory reports',
                   archive_path, len(files_added))
      archived_list += files_added
      index += 1

  def _ArchiveOne(self, dir_to_archive: str, archive_path: str,
                  archived_list: List[str]) -> Optional[List[str]]:
    """Archives files to one archive and checks the integrity.

    The archive only allows directory and regular file. If a files is already
    archived previously or the archive already reach the ARCHIVE_SIZE_THRESHOLD,
    it will skip the file.

    Returns:
      A list of files if it archives them correctly; otherwise, return None.
    """
    archive_size = 0
    files_added = []

    def Filter(tarinfo: tarfile.TarInfo) -> Optional[tarfile.TarInfo]:
      nonlocal archive_size
      if tarinfo.isdir():
        return tarinfo
      # Only allows directory and regular file.
      if not tarinfo.isfile():
        return None
      if tarinfo.name in archived_list:
        return None
      if archive_size >= self.ARCHIVE_SIZE_THRESHOLD:
        return None
      archive_size += tarinfo.size
      files_added.append(tarinfo.name)
      return tarinfo

    try:
      with tarfile.open(archive_path, 'w') as tar:
        tar.add(dir_to_archive, filter=Filter)

      # Check the tar file integrity.
      # tarfile.is_tarfile() cannot detect corrupted content, so we use
      # getmembers here.
      with tarfile.open(archive_path, 'r') as tar:
        tar.getmembers()

      return files_added
    except Exception:
      logging.exception('Failed to archive Factory Reports')
      os.remove(archive_path)
      return None

  def _CleanUp(self, dir_to_clean: str):
    shutil.move(dir_to_clean, self.finished_report_dir)


class IConnection(abc.ABC):

  @abc.abstractmethod
  def SendFile(self, local_path: str, target_path: str) -> bool:
    """Uploads a file to the destination path."""
    return NotImplemented

  @abc.abstractmethod
  def CheckIntegrity(self, local_path: str, target_path: str) -> bool:
    """Checks the file integrity."""
    return NotImplemented


class SFTP(IConnection):

  TARGET_NOT_EXIST_RE = re.compile(r'dest .* No such file or directory', re.M)

  def __init__(self, hostname: str, port: Union[str, int], account: str,
               key_path: str):
    self.hostname = hostname
    self.port = str(port)
    self.account = account
    self.key_path = key_path

  def SendFile(self, local_path, target_path):
    logging.info('Uploading %s to %s', local_path, target_path)
    returncode, unused_outs, errs = self._SFTPCommand(
        f'put {local_path} {target_path}')
    if returncode != 0:
      return False
    if self.TARGET_NOT_EXIST_RE.match(errs):
      logging.error(
          'Please use `mkdir` to create target_dir before running this script')
      raise ValueError('No such directory on SFTP server')
    # We can't check if file uploaded successfully, so we need to check the
    # file size on the server.
    returncode, outs, unused_errs = self._SFTPCommand(f'ls -l {target_path}')
    file_size = os.path.getsize(local_path)
    if returncode != 0 or str(file_size) not in outs:
      return False
    logging.info('Uploaded successfully')
    return True

  def CheckIntegrity(self, local_path, target_path):
    with tempfile.NamedTemporaryFile(delete=False) as f:
      temp_file = f.name
    try:
      logging.info(
          'Downloading the file %s from server and checking the hash '
          'value', target_path)
      returncode, unused_outs, unused_errs = self._SFTPCommand(
          f'get {target_path} {temp_file}')
      if returncode != 0:
        return False
      local_hash = self._MD5InBase64(local_path)
      target_hash = self._MD5InBase64(temp_file)
      logging.info('local hash = %s, target hash = %s', local_hash, target_hash)
      if local_hash != target_hash:
        logging.warning('Does not match!')
        return False
    finally:
      if os.path.exists(temp_file):
        os.unlink(temp_file)
    return True

  def _MD5InBase64(self, file_path: str) -> str:
    """Returns the MD5 hash value of the file in base64.

    `gsutil ls -L` shows md5 hash value which is base64-encoding.  To debug
    eaiser, this function also returns md5 hash value in base64.
    """
    with open(file_path, 'rb') as f:
      hash_value = base64.b64encode(hashlib.md5(f.read()).digest())
    return hash_value

  def _SFTPCommand(self, command: str) -> Tuple[int, str, str]:
    with subprocess.Popen([
        'sftp', '-oStrictHostKeyChecking=no', '-i', self.key_path, '-P',
        self.port, f'{self.account}@{self.hostname}'
    ], stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                          encoding='utf-8') as p:
      outs, errs = p.communicate(command)
    return p.returncode, outs, errs


class ArchiveUploader:

  def __init__(self, connection: IConnection, archive_dir: str,
               finished_archive_dir: str):
    self.connection = connection
    self.archive_dir = archive_dir
    self.finished_archive_dir = finished_archive_dir
    logging.info('Initialized ArchiveUploader')

  def UploadArchive(self, target_dir: str, hash_check: bool) -> Status:
    """Uploads a Report Archive in the directory to the SFTP server.

    Returns:
      Status Enum.
    """
    files = os.listdir(self.archive_dir)
    file_name_to_upload = None
    files.sort()
    for file_name in files:
      if file_name.endswith('.tmp'):
        continue
      file_name_to_upload = file_name
      break
    if not file_name_to_upload:
      return Status.NO_FILE

    local_path = os.path.join(self.archive_dir, file_name_to_upload)
    target_path = os.path.join(target_dir, file_name_to_upload)
    if not self.connection.SendFile(local_path, target_path):
      return Status.FAIL

    # Checks the file integrity.
    if not hash_check or not self.connection.CheckIntegrity(
        local_path, target_path):
      return False
    self._CleanUp(local_path)
    return Status.SUCCESS

  def _CleanUp(self, archive_to_clean: str):
    shutil.move(archive_to_clean, self.finished_archive_dir)


def main():
  args = ParseArgument()

  if not os.access(args.key_path, os.R_OK):
    raise PermissionError(f'Cannot read the private key file: {args.key_path}')
  if not os.access(args.factory_report_dir, os.R_OK | os.W_OK):
    raise PermissionError('Cannot access factory_report_dir: '
                          f'{args.factory_report_dir}')

  log_path = os.path.join(args.log_dir, 'upload_reports_sftp.log')
  archive_dir = os.path.join(args.log_dir, 'archive')
  TryMakeDirs(archive_dir)
  finished_report_dir = os.path.join(args.log_dir, 'finished', 'report')
  TryMakeDirs(finished_report_dir)
  finished_archive_dir = os.path.join(args.log_dir, 'finished', 'archive')
  TryMakeDirs(finished_archive_dir)

  InitLogging(log_path)

  report_finder = ReportFinder(args.factory_report_dir)
  report_archiver = ReportArchiver(report_finder, archive_dir,
                                   finished_report_dir)
  sftp = SFTP(args.hostname, args.port, args.account, args.key_path)
  archive_uploader = ArchiveUploader(sftp, archive_dir, finished_archive_dir)
  while True:
    archive_result = Status.SUCCESS
    upload_result = Status.SUCCESS
    while archive_result == Status.SUCCESS:
      archive_result = report_archiver.ProduceArchives()
    while upload_result == Status.SUCCESS:
      upload_result = archive_uploader.UploadArchive(args.target_dir,
                                                     args.hash_check)
    # If there is no valid report directory and no archive, sleep for a while.
    if archive_result == upload_result == Status.NO_FILE:
      sleep_in_sec = 6 * 60 * 60  # 6 hours
      logging.info('There\'s no report/archive to process, sleep %s seconds',
                   sleep_in_sec)
      time.sleep(sleep_in_sec)
    # If it failed to archive/upload, sleep for a minute.
    else:
      sleep_in_sec = 60
      logging.info('Process failed, sleep %s seconds', sleep_in_sec)
      time.sleep(sleep_in_sec)


if __name__ == '__main__':
  main()
