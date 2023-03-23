# Copyright 2023 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

import logging
from typing import Callable, Dict, Optional, Tuple

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

  def __del__(self):
    self._f.close()

  def GetCurRecord(self) -> Optional[IRecord]:
    return self._cur_record

  def __iter__(self):
    return self

  def __next__(self):
    """Keeps reading from the file until a valid record is found."""
    # Continue reading from the file descriptor.
    for line in self._f:
      try:
        self._cur_record = self._loader(line, self._validate)
        return self._cur_record
      except Exception as err:
        logging.warning('Record %s in %s is invalid! %r', line,
                        self._input_path, err)
    self._cur_record = None
    raise StopIteration


def ExtractAndWriteRecordByTestRun(reader, output_dir: str, output_fname: str):
  """Extracts records based on the test run event.

  The extraction starts when reading the STARTED event and stops when reading
  the COMPLETED event. Only testlog and /var/log/messages contains such
  events. The extracted records will be written under
  `{output_dir}/{test_run_name}/{output_fname}`.

  Args:
    reader: A file reader which reads new record on every iteration.
    output_dir: The output directory.
    output_fname: The output filename.
  """
  raise NotImplementedError


def GetTestRunStartEndTime(reader) -> Dict[str, Tuple]:
  """Gets the start and end time of all the test run.

  Args:
    reader: A file reader which reads new record on every iteration.

  Returns:
    A dictionary whose key is the test_run_name and values are start and
    end time.
  """
  raise NotImplementedError


def ExtractAndWriteRecordByTimeStamp(reader, output_dir: str, output_fname: str,
                                     timestamps: Dict[str, Tuple]):
  """Extracts records based on the timestamps.

  The extractions start and stop based on the given start and end time. The
  extracted records will be written under
  `{output_dir}/{test_run_name}/{output_fname}`.

  Args:
    reader: A file reader which reads new record on every iteration.
    output_dir: The output directory.
    output_fname: The output filename.
    timestamps: A dictionary whose key is the test_run_name and values are
      start and end time.
  """
  raise NotImplementedError
