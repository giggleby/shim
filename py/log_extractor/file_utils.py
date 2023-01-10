# Copyright 2023 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

import logging

from cros.factory.log_extractor.record import LogExtractorRecord
from cros.factory.utils import type_utils


class LogExtractorError(type_utils.Error):
  pass


class LogExtractorFileReader:
  """A JSON file reader which loads and buffers the current JSON record.

  The format of the input file should be one JSON record per line, and each
  record should contain at least a field called `time`.
  """

  def __init__(self, f_name):
    self._f_name = f_name
    self._f = open(self._f_name, 'r', encoding='utf-8')  # pylint: disable=consider-using-with
    self._cur_record = None
    if not self.ReadNextValidRecord():
      logging.warning('The content of file %s is empty!', self.f_name)

  def __del__(self):
    self._f.close()

  def GetCurRecord(self):
    return self._cur_record

  def ReadNextValidRecord(self):
    """Reads and filters a new valid JSON record from the file."""
    line = self._f.readline()
    if line:
      try:
        self._cur_record = LogExtractorRecord.Load(line)
      except Exception as err:
        logging.warning('JSON record %s in %s is invalid! %r', line,
                        self._f_name, err)
        return self.ReadNextValidRecord()
    else:
      self._cur_record = None
    return self._cur_record

  def __lt__(self, other):
    return self._cur_record < other._cur_record
