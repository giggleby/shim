#!/usr/bin/env python3
#
# Copyright 2023 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

import argparse
import heapq
import json
import logging

from cros.factory.log_extractor.file_utils import LogExtractorFileReader
from cros.factory.log_extractor.record import LogExtractorRecord


DESCRIPTION = """
  This is a tool to filter and merge JSON records. The format of the input file
  should be one JSON record per line, and each record should contain at least a
  field called `time`.
  Given several input files, the tool will filter the JSON records using the
  given keys, and merge the records according to the the value of field `time`.
"""
EXAMPLES = """
  Examples:

  To keep only `time` and `message` fields in testlog.json, run:
  > factory_log_extractor.py testlog.json \
      -k time message \
      -o filtered_testlog.json \
      && cat filtered_testlog.json
    {"time": 1664758861.421799, "message": "Testlog(dade3d78-909d-4171-ab7d-297e2e17cd2b) is capturing logging at level INFO"}
    {"time": 1664758861.4335938, "message": "Starting goofy server"}
    {"time": 1664758861.4361095, "message": "Running command: \"mount /dev/mapper/encstateful -o commit=0,remount\""}
    {"time": 1664758861.4400852, "message": "Running command: \"mount /dev/mmcblk0p1 -o commit=0,remount\""}
"""

DEFAULT_FIELDS_TO_KEEP = [
    # General fields to keep
    'time',
    # Below are the fields defined in testlog and are categorized by the event
    # types:
    # station.init
    'count',
    'success',
    # station.message
    'filePath',
    'logLevel',
    'message',
    # station.status
    'testRunId',
    'testName',
    'testType',
    'status',
    'arguments',
    'startTime',
    'endTime',
]


def ExtractAndMergeLogs(input_paths, output_path, fields_to_keep):

  def _RemoveFields(record: LogExtractorRecord, fields_to_keep):
    """Inplace removes some fields from the JSON record."""
    for to_remove in record.keys() - fields_to_keep:
      record.pop(to_remove)

  reader_heap = []
  for p in input_paths:
    reader = LogExtractorFileReader(p)
    if reader.GetCurRecord():
      reader_heap.append(reader)
  heapq.heapify(reader_heap)

  with open(output_path, 'w', encoding='utf-8') as output_f:
    while reader_heap:
      reader = heapq.heappop(reader_heap)
      record = reader.GetCurRecord()
      if fields_to_keep:
        _RemoveFields(record, fields_to_keep)
      if record:
        output_f.write(json.dumps(record, sort_keys=True) + '\n')
      if not reader.ReadNextValidRecord():
        continue
      heapq.heappush(reader_heap, reader)


def ParseArgument():
  parser = argparse.ArgumentParser(
      description=DESCRIPTION, epilog=EXAMPLES,
      formatter_class=argparse.RawDescriptionHelpFormatter)
  # TODO: Filter the given logs based on a test-run id.
  parser.add_argument('--keep', '-k', nargs='+', type=str,
                      default=DEFAULT_FIELDS_TO_KEEP, metavar='key',
                      help=('Only keep certain fields in a json record.'))
  parser.add_argument('path', type=str, nargs='+', metavar='path',
                      help=('Path to the JSON files.'))
  parser.add_argument('--output', '-o', type=str, metavar='path',
                      help=('Path to store the output file.'), required=True)

  return parser.parse_args()


def main():
  logging.basicConfig(level=logging.INFO)
  args = ParseArgument()
  logging.info('Extracting logs from %r to %s ...', args.path, args.output)
  logging.info('Fields to keep: %r', args.keep)
  ExtractAndMergeLogs(args.path, args.output, args.keep)


if __name__ == '__main__':
  main()
