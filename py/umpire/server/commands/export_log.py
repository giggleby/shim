# Copyright 2019 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Export specific log, such as factory log, DUT report, and ECHO codes.

See LogExporter comments for usage.
"""

from collections import defaultdict
import datetime
import os

from cros.factory.umpire import common
from cros.factory.utils import process_utils


class LogExporter:

  def __init__(self, env):
    """Constructor.

    Args:
      env: UmpireEnv object.
    """
    self._env = env

  def DateRange(self, start_date, end_date):
    for n in range(int((end_date - start_date).days) + 1):
      yield start_date + datetime.timedelta(days=n)

  def GetBytes(self, size, unit):
    if unit == 'MB':
      return size * 1024**2
    if unit == 'GB':
      return size * 1024**3
    raise ValueError('This is not a valid unit')

  def CompressFilesFromListToPath(self, src_dir_with_files, dst_path):
    cmd = ['tar', '-cjf', dst_path]
    for src_dir, file_list in src_dir_with_files.items():
      cmd.append('-C')
      cmd.append(src_dir)
      cmd.extend(file_list)
    process_utils.Spawn(cmd, check_call=True, log=True)

  def CompressFilesFromList(self, index, date, src_dir_with_files, dst_dir):
    tar_file = f'{date}-{index}.tar.bz2'
    dst_path = os.path.join(dst_dir, tar_file)
    self.CompressFilesFromListToPath(src_dir_with_files, dst_path)
    return tar_file

  def CompressFilesLimitedMaxSize(self, start_date, end_date, root_dir, dst_dir,
                                  max_archive_size):
    file_list = []
    current_archive_size = 0
    tar_files = []
    start_date_str = start_date.strftime('%Y%m%d')
    end_date_str = end_date.strftime('%Y%m%d')
    date_str = start_date_str + '-' + end_date_str
    src_dir_with_files = defaultdict(list)
    for date in self.DateRange(start_date, end_date):
      sub_str = date.strftime('%Y%m%d')
      src_dir = os.path.join(root_dir, sub_str)
      if not os.path.isdir(src_dir) or not os.listdir(src_dir):
        continue
      for (root, unused_dirs, src_files) in os.walk(src_dir):
        for src_filename in src_files:
          src_filepath = os.path.join(root, src_filename)
          relpath = os.path.relpath(src_filepath, src_dir)
          file_size = os.path.getsize(src_filepath)
          if current_archive_size + file_size > max_archive_size:
            if not file_list:
              raise common.UmpireError(
                  'Failed to export: Your file size large than maximum archive'
                  'size, please enlarge the maximum archive size.')
            tar_files.append(
                self.CompressFilesFromList(
                    len(tar_files), date_str, src_dir_with_files, dst_dir))
            current_archive_size = file_size
            file_list = [relpath]
            src_dir_with_files = defaultdict(list)
            src_dir_with_files[src_dir] = [relpath]
          else:
            current_archive_size += file_size
            file_list.append(relpath)
            src_dir_with_files[src_dir].append(relpath)

    if file_list:
      tar_files.append(
          self.CompressFilesFromList(
              len(tar_files), date_str, src_dir_with_files, dst_dir))

    return tar_files

  def ExportLog(
      self, dst_dir, log_type, split_size, start_date_str, end_date_str):
    """Compress and export a specific log, such as factory log, DUT report,
    or csv files.

    Args:
      dst_dir: the destination directory to export the specific log.
      log_type: download type of the log, e.g. log, report, csv.
      split_size: maximum size of the archives.
                  (format: {'size': xxx, 'unit': 'MB'/'GB'})
      start_date: start date (format: yyyymmdd)
      end_date: end date (format: yyyymmdd)

    Returns:
      {
        'messages': array (messages of ExportLog)
        'log_paths': array (files paths of compressed files)
      }
    """
    umpire_data_dir = self._env.umpire_data_dir
    sub_dir = {
        'csv': 'csv',
        'report': 'report',
        'log': 'aux_log'
    }[log_type]
    split_bytes = self.GetBytes(split_size['size'], split_size['unit'])
    messages = []

    try:
      if log_type == 'csv':
        compressed_file_name = 'csv.tar.bz2'
        dst_path = os.path.join(dst_dir, compressed_file_name)
        self.CompressFilesFromListToPath({umpire_data_dir: [sub_dir]}, dst_path)

        if os.path.isfile(dst_path):
          return {
              'messages': messages,
              'log_paths': [compressed_file_name],
          }

        messages.append(f'{compressed_file_name} does not exist')
        return {
            'messages': messages,
            'log_paths': [],
        }

      if log_type in ('report', 'log'):
        start_date = datetime.datetime.strptime(start_date_str, '%Y%m%d').date()
        end_date = datetime.datetime.strptime(end_date_str, '%Y%m%d').date()
        root_dir = os.path.join(umpire_data_dir, sub_dir)
        tar_files_list = []
        no_logs = True
        if os.path.isdir(root_dir) and os.listdir(root_dir):
          no_logs = False
          tar_files_list = self.CompressFilesLimitedMaxSize(
              start_date, end_date, root_dir, dst_dir, split_bytes)
        if no_logs:
          messages.append(f'no {log_type}s for {start_date} ~ {end_date}')
        return {
            'messages': messages,
            'log_paths': tar_files_list,
        }
      raise common.UmpireError(f'Failed to export {log_type}: No such type')
    except Exception as e:
      raise common.UmpireError(f'Failed to export {log_type}\n{e!r}')
