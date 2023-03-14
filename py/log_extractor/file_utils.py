# Copyright 2023 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

import logging
import os
from typing import Callable, Dict, Optional, Tuple

from cros.factory.log_extractor.record import IRecord
from cros.factory.log_extractor import test_run_handler
from cros.factory.log_extractor.test_run_handler import TestRunStatus
from cros.factory.utils import file_utils


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


class LogExtractorStateMachine:
  """A state machine which performs file I/O given different state."""

  def __init__(self):
    """Initializes the test_run_id to file descriptor map.

    Since tests might run in parallel, we need to store all running tests.
    """
    self._f_map = {}

  def BeginTestRun(self, test_run_id: str, output_path: str):
    """Opens a file of path `output_path` and records its id `test_run_id`."""
    if test_run_id in self._f_map:
      logging.warning('Test %s has already started.', test_run_id)
      return

    fd = open(output_path, 'w', encoding='utf-8')  # pylint: disable=consider-using-with
    self._f_map[test_run_id] = fd
    logging.info('Test %s starts. Output path: %s', test_run_id, output_path)

  def EndTestRun(self, test_run_id: str):
    """Closes the file descriptor of id `test_run_id`."""
    if test_run_id not in self._f_map:
      logging.warning('Test %s ends without starting.', test_run_id)
      return

    logging.info('Test %s ends.', test_run_id)
    self._f_map[test_run_id].close()
    self._f_map.pop(test_run_id)

  def WriteRecord(self, test_run_id: Optional[str], record: IRecord):
    """Write a record to the current running test(s).

    Args:
      test_run_id: The test run id that generates the record. If set to None,
        write to all running tests.
      record: a record of type IRecord.
    """
    if test_run_id in self._f_map:
      self._f_map[test_run_id].write(str(record) + '\n')
    else:
      # Cannot determine which test run the logs belongs to.
      # Write to all running tests.
      for f in self._f_map.values():
        f.write(str(record) + '\n')

  def IsTestRunning(self) -> bool:
    """Check if there's any test running."""
    return bool(self._f_map)


def GetExtractedLogOutputPath(test_name: str, test_run_id: str, root: str,
                              fname: str) -> str:
  test_run_name = f'{test_name}-{test_run_id}'
  test_run_dir = os.path.join(root, test_run_name)
  file_utils.TryMakeDirs(test_run_dir)
  return os.path.join(test_run_dir, fname)

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
  state_machine = LogExtractorStateMachine()
  for record in reader:
    status = test_run_handler.ParseStatus(record)
    test_name, test_run_id = test_run_handler.TestRunNameHandler().Parse(record)

    if status in (TestRunStatus.STARTED, TestRunStatus.COMPLETED):
      if not test_name or not test_run_id:
        logging.warning('Record %s does not contain test run name info.',
                        str(record))
        continue

    if status == TestRunStatus.STARTED:
      output_path = GetExtractedLogOutputPath(test_name, test_run_id,
                                              output_dir, output_fname)
      state_machine.BeginTestRun(test_run_id, output_path)

    if state_machine.IsTestRunning():
      state_machine.WriteRecord(test_run_id, record)

    if status == TestRunStatus.COMPLETED:
      state_machine.EndTestRun(test_run_id)

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
