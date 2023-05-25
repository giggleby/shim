# Copyright 2023 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

import logging
import os
from typing import Callable, Dict, List, NamedTuple, Optional, Tuple

import cros.factory.log_extractor.record as record_module
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

  def __init__(self, input_path: str, loader: Callable[[str, bool],
                                                       record_module.IRecord],
               validate: bool = True):
    self._input_path = input_path
    self._f = open(self._input_path, 'r', encoding='utf-8')  # pylint: disable=consider-using-with
    self._validate = validate
    self._loader = loader
    self._cur_record = None

  def __del__(self):
    self._f.close()

  def GetCurRecord(self) -> Optional[record_module.IRecord]:
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

  def YieldByEventType(self, types: List[str]):
    for record in self:
      if record.GetEventType() in types:
        yield record


class TestRunInfo(NamedTuple):

  test_name: str
  test_run_id: str
  status: TestRunStatus
  time: float

class LogExtractorStateMachine:
  """A state machine which performs file I/O given different state."""

  def __init__(self):
    """Initializes the test_run_id to MetaData map.

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

  def WriteRecord(self, test_run_id: Optional[str],
                  record: record_module.IRecord):
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

  def GetRunningTests(self):
    return self._f_map.keys()


def GetExtractedLogOutputPath(test_name: str, test_run_id: str, root: str,
                              fname: str) -> str:
  output_path = f'{root}/{test_name}-{test_run_id}/summary/{fname}'
  file_utils.TryMakeDirs(os.path.dirname(output_path))
  return output_path


def ExtractAndWriteRecordByTestRun(
    reader, output_dir: str, output_fname: str,
    start_event_cnt_map: Dict[str, int]) -> List[TestRunInfo]:
  """Extracts records based on the test run status.

  Normally, the log extraction should start when reading the STARTING event and
  should stop when reading the COMPLETED (PASS/FAIL) event. However, there
  might be several STARTING and COMPLETED events if the test involes reboot.

  Below are examples of possible test status sequences:
  For test without reboot:
    STARTING -> PASS/FAIL
  For test with one intentional reboot:
    STARTING (pre-shutdown) -> FAIL (pre-shutdown) -> (DUT reboots)
    -> STARTING (post-shutdown)-> PASS/FAIL (post-shutdown)
  For test with one un-intentional reboot:
    STARTING -> (DUT reboots) -> STARTING -> FAIL

  To address this, we count the number of start event beforehand and store it
  in `start_event_cnt_map`. When reading the COMPLETED event, we check if the
  current number of start event count matches the one stored in
  `start_event_cnt_map`. If yes, then stops log extraction.

  Only testlog and /var/log/messages contains test run status. The extracted
  records will be written under
  `{output_dir}/{test_name}-{test_run_id}/summary/{output_fname}`.

  Args:
    reader: A file reader which reads new record on every iteration.
    output_dir: The output directory.
    output_fname: The output filename.
    start_event_cnt_map: A dictionary which contains test_run_id to
      start_event_cnt map.

  Returns:
    A list of type TestRunInfo. It contains non-duplicated test run events
    which will be used to extract logs on files that do not contain test
    run event.
  """
  state_machine = LogExtractorStateMachine()
  cur_start_event_cnt_map = {}
  test_run_info_list = []
  for record in reader:
    status = test_run_handler.StatusHandler().Parse(record)
    test_name, test_run_id = test_run_handler.TestRunNameHandler().Parse(record)
    if status in (TestRunStatus.STARTED, TestRunStatus.COMPLETED):
      if not test_name or not test_run_id:
        logging.warning('Record %s does not contain test run name info.',
                        str(record))
        continue

    if test_run_id and test_run_id not in start_event_cnt_map:
      logging.warning('Skip recording %s.', test_run_id)
      continue

    if status == TestRunStatus.STARTED:
      if test_run_id in cur_start_event_cnt_map:
        cur_start_event_cnt_map[test_run_id] += 1
      else:
        cur_start_event_cnt_map[test_run_id] = 1
        output_path = GetExtractedLogOutputPath(test_name, test_run_id,
                                                output_dir, output_fname)
        state_machine.BeginTestRun(test_run_id, output_path)
        test_run_info_list.append(
            TestRunInfo(test_name, test_run_id, status, record.GetTime()))

    if state_machine.IsTestRunning():
      state_machine.WriteRecord(test_run_id, record)

    if status == TestRunStatus.COMPLETED:
      if (cur_start_event_cnt_map.get(test_run_id,
                                      0) == start_event_cnt_map[test_run_id]):
        state_machine.EndTestRun(test_run_id)
        test_run_info_list.append(
            TestRunInfo(test_name, test_run_id, status, record.GetTime()))

  running_tests = state_machine.GetRunningTests()
  logging.warning('Tests that are still running: %r', running_tests)
  return test_run_info_list

# pylint: disable=unused-argument
def ExtractAndWriteRecordByTimeStamp(reader, output_dir: str, output_fname: str,
                                     test_run_info_dict: List[TestRunInfo]):
  """Extracts records based on the timestamps.

  The extractions start and stop based on the given start and end time. The
  extracted records will be written under
  `{output_dir}/{test_name}-{test_run_id}/summary/{output_fname}`.

  Args:
    reader: A file reader which reads new record on every iteration.
    output_dir: The output directory.
    output_fname: The output filename.
    test_run_info_list: A list of type TestRunInfo.
  """


def GetStartEventCnt(reader) -> Dict[str, int]:
  start_cnt = {}
  for record in reader:
    status = test_run_handler.StatusHandler().Parse(record)
    _, test_run_id = test_run_handler.TestRunNameHandler().Parse(record)
    if status != TestRunStatus.STARTED or test_run_id is None:
      continue

    start_cnt[test_run_id] = start_cnt.get(test_run_id, 0) + 1

  return start_cnt


def ExtractLogsAndWriteRecord(output_root: str, factory_log: str,
                              var_log_msg: str, system_logs: Tuple = ()):
  """Extracts JSON logs to {output_root}/{test_name}-{test_run_id}/summary."""
  # We use factory log as source of truth to generate test run info for two
  # reasons:
  # - We often only care about the logs generated after toolkit is installed.
  # - If user has cleared the factory log using e.g. `factory_restart` before,
  #   the logs in factory logs and system logs will not match. e.g. The system
  #   log contains a test start event `A` while the factory logs does not.
  #   In this case, we often don't care about the un-matched logs.
  factory_log_reader = LogExtractorFileReader(
      factory_log, record_module.TestlogRecord.FromJSON)
  start_event_cnt_map = GetStartEventCnt(factory_log_reader)

  factory_log_reader = LogExtractorFileReader(
      factory_log, record_module.TestlogRecord.FromJSON)
  test_run_info_list = ExtractAndWriteRecordByTestRun(
      factory_log_reader, output_root, 'factory', start_event_cnt_map)

  var_log_msg_reader = LogExtractorFileReader(
      var_log_msg, record_module.SystemLogRecord.FromJSON)
  ExtractAndWriteRecordByTestRun(var_log_msg_reader, output_root, 'message',
                                 start_event_cnt_map)

  for system_log in system_logs:
    system_log_reader = LogExtractorFileReader(
        system_log, record_module.SystemLogRecord.FromJSON)
    ExtractAndWriteRecordByTimeStamp(system_log_reader, output_root,
                                     os.path.basename(system_log),
                                     test_run_info_list)
