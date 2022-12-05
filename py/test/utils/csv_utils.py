# Copyright 2023 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

import csv
import glob
import os
import re
from typing import IO, List

from cros.factory.test.env import paths
from cros.factory.utils import file_utils


_RE_CSV_FILENAME_PATTERN = re.compile(r'^\w+$')


class CSVManager:
  """A helper class to manage CSV entries that are stored locally"""

  def __init__(self, csv_dir: str = paths.DATA_CSV_DIR):
    self._csv_dir = csv_dir

  def Append(self, csv_filename: str, entry: List):
    """Save a CSV entry locally.

    Save a CSV entry to a local file. The entries in the local file can be
    uploaded to the factory server later.

    This function does not access the factory server. It can be called without
    internet access.

    Args:
      csv_filename: The CSV file name.
      entry: A list of values, represents a row in the CSV file.
    """
    if not _RE_CSV_FILENAME_PATTERN.match(csv_filename):
      raise ValueError(f'csv_filename: {csv_filename!r} is invalid')

    csv_path = self._GetCSVPath(csv_filename)
    context = file_utils.FileLockContextManager(csv_path, 'a')
    with context as f:
      assert f is not None
      writer = csv.writer(f)
      writer.writerow(entry)
      f.flush()
    context.Close()

  def UploadAll(self, factory_server_proxy):
    """Upload all content of local CSV files.

    Upload the CSV entries from local filesystem to a factory server. If there
    is any error during upload, the functions writes the data that are not yet
    uploaded back into device data, and raises the exception.

    The pytest `sync_factory_server` calls this function by default.

    Args:
      factory_server_proxy: a proxy object of a factory server.
    """
    for csv_path in glob.iglob(self._GetCSVPath('*')):
      self._UploadOneFile(factory_server_proxy, csv_path)

  def _UploadOneFile(self, factory_server_proxy, csv_path):
    """Upload the content of a local CSV file.

    The function upload each entry in the CSV file one by one. If there are any
    failure, the function will update the file by removing the uploaded entries.
    So they won't be uploaded again on the next try.

    If the function finishes successfully, the CSV file will become empty.

    Args:
      factory_server_proxy: a proxy object of a factory server.
      csv_path: the path of the CSV file to upload.
    """
    csv_filename = self._GetCSVFilename(csv_path)

    context = file_utils.FileLockContextManager(csv_path, 'r+')
    try:
      with context as f:
        assert f is not None
        reader = csv.reader(f)
        for row in reader:
          try:
            factory_server_proxy.UploadCSVEntry(csv_filename, row)
          except Exception:
            self._WriteRestOfFile(f, row)
            raise
        self._ClearFile(f)
    finally:
      context.Close()

  def _GetCSVPath(self, csv_filename: str):
    return os.path.join(self._csv_dir, f'{csv_filename}.csv')

  @classmethod
  def _GetCSVFilename(cls, csv_path: str):
    basename = os.path.basename(csv_path)
    return os.path.splitext(basename)[0]

  @classmethod
  def _WriteRestOfFile(cls, f: IO, failed_row):
    rest_of_file = f.read()
    cls._ClearFile(f)
    writer = csv.writer(f)
    writer.writerow(failed_row)
    f.write(rest_of_file)
    f.flush()

  @classmethod
  def _ClearFile(cls, f: IO):
    f.seek(0)
    f.truncate(0)
    f.flush()
