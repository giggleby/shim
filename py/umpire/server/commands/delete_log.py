# Copyright 2022 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.
"""Delete specific log, such as factory log, DUT report, or csv files."""

import datetime
import os
import shutil

from cros.factory.umpire import common


class LogDeleter:

  def __init__(self, env):
    """Constructor.

    Args:
      env: UmpireEnv object.
    """
    self._env = env

  def DateRange(self, start_date: datetime.datetime,
                end_date: datetime.datetime):
    """Yields the date between start_date and end_date inclusively.

    Args:
      start_date: start date (format: yyyy-mm-dd 00:00:00, type: datetime)
      end_date: end date (format: yyyy-mm-dd 00:00:00, type: datetime)
    """
    for n in range(int((end_date - start_date).days) + 1):
      yield start_date + datetime.timedelta(days=n)

  def DeleteLog(self, log_type, start_date_str, end_date_str):
    """Delete a specific log, such as factory log, DUT report,
    or csv files.

    Args:
      log_type: download type of the log, e.g. log, report, csv.
      start_date: start date (format: yyyymmdd)
      end_date: end date (format: yyyymmdd)

    Returns:
      {
        'messages': array (messages of DeleteLog)
      }
    """
    umpire_data_dir = self._env.umpire_data_dir
    sub_dir = {
        'csv': 'csv',
        'report': 'report',
        'log': 'aux_log'
    }[log_type]
    messages = []

    try:
      if log_type == 'csv':
        dst_path = os.path.join(umpire_data_dir, sub_dir)
        if not os.path.isdir(dst_path) or not os.listdir(dst_path):
          messages.append('CSV file does not exist')
        else:
          shutil.rmtree(dst_path)
          messages.append('CSV file removed successfully')
        return {
            'messages': messages,
        }

      if log_type in ('report', 'log'):
        start_date = datetime.datetime.strptime(start_date_str, '%Y%m%d').date()
        end_date = datetime.datetime.strptime(end_date_str, '%Y%m%d').date()
        no_logs = True
        for date in self.DateRange(start_date, end_date):
          date_str = date.strftime('%Y%m%d')
          src_dir = os.path.join(umpire_data_dir, sub_dir, date_str)
          if not os.path.isdir(src_dir) or not os.listdir(src_dir):
            continue
          no_logs = False
          shutil.rmtree(src_dir)

        if no_logs:
          messages.append(f'no {log_type}s for {start_date} ~ {end_date}')
        else:
          messages.append('File removed successfully')
        return {
            'messages': messages,
        }
      raise common.UmpireError(f'Failed to export {log_type}: No such type')
    except Exception as e:
      raise common.UmpireError(f'Failed to export {log_type}\n{e!r}')
