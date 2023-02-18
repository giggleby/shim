# Copyright 2023 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

import logging
from typing import Callable, Optional

from cros.factory.log_extractor.record import IRecord


class LogExtractorFileReader:
  """A file reader which loads and buffers the current record.

  The format of the input file should be one record per line.

  Args:
    input_path: Path to a input file.
    loader: A record loader which takes a line from the input file and a bool
      indicating whether to validate the record or not, as input args.
    validate: To validate the fields in a record or not.
  """

  def __init__(self, input_path: str, loader: Callable[[str, bool], IRecord],
               validate: bool = True):
    self._input_path = input_path
    self._f = open(self._input_path, 'r', encoding='utf-8')  # pylint: disable=consider-using-with
    self._validate = validate
    self._loader = loader
    self._cur_record = None
    if not self.ReadNextValidRecord():
      logging.warning('The content of file %s is empty!', self._input_path)

  def __del__(self):
    self._f.close()

  def GetCurRecord(self) -> Optional[IRecord]:
    return self._cur_record

  def ReadNextValidRecord(self) -> Optional[IRecord]:
    """Reads and filters a new valid record from the file."""
    line = self._f.readline()
    if line:
      try:
        self._cur_record = self._loader(line, self._validate)
      except Exception as err:
        logging.warning('Record %s in %s is invalid! %r', line,
                        self._input_path, err)
        return self.ReadNextValidRecord()
    else:
      self._cur_record = None
    return self._cur_record

  def __lt__(self, other):
    return self._cur_record < other._cur_record
