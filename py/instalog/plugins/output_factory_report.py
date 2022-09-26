#!/usr/bin/env python3
#
# Copyright 2021 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.
"""Output factory report plugin.

A plugin to process archives which are uploaded py partners. This plugin will do
the following things:
  1. Download an archive from Google Cloud Storage
  2. Decompress factory reports from the archive
  3. Process and parse factory reports
  4. Generate report events with some information
  5. Generate process events with process status during parsing
"""

import abc
import copy
import json
import logging
import multiprocessing
import os
import re
import shutil
import subprocess
import tarfile
import time
import traceback
import zipfile

import yaml

from cros.factory.instalog import datatypes
from cros.factory.instalog import log_utils
from cros.factory.instalog import plugin_base
from cros.factory.instalog.utils.arg_utils import Arg
from cros.factory.instalog.utils import file_utils
from cros.factory.instalog.utils import gcs_utils
from cros.factory.instalog.utils import process_utils
from cros.factory.instalog.utils import time_utils
from cros.factory.instalog.utils import type_utils


_PROCESSES_NUMBER = 20
REPORT_EVENT_FIELD = {
    'apiVersion', 'dutDeviceId', 'stationDeviceId', 'stationInstallationId'
}
PATTERN_WP_STATUS = re.compile(r'WP: status: (\w+)')
PATTERN_WP = re.compile(r'WP: write protect is (\w+)\.')
PATTERN_SERIAL_NUMBER = re.compile(rb'^\s*serial_number: .*$', re.M)
PATTERN_MLB_SERIAL_NUMBER = re.compile(rb'^\s*mlb_serial_number: .*$', re.M)
PATTERN_HWID_LOG = re.compile(r'.+ Generated HWID: (?P<hwid>.+ [A-Z0-9\-].+)')
yaml_loader = yaml.CBaseLoader if yaml.__with_libyaml__ else yaml.BaseLoader


class OutputFactoryReport(plugin_base.OutputPlugin):

  ARGS = [
      # TODO(chuntsen): Remove key_path argument since we don't use it anymore.
      Arg(
          'key_path', str,
          'Path to BigQuery/CloudStorage service account JSON key file.  If '
          'set to None, the Google Cloud client will use the default service '
          'account which is set to the environment variable '
          'GOOGLE_APPLICATION_CREDENTIALS or Google Cloud services.',
          default=None),
      Arg(
          'archive_batch_size', int,
          'Size in bytes of archives to process in parallel.  Default is '
          '50GB.', default=50 * 1024**3),
  ]

  def __init__(self, *args, **kwargs):
    super().__init__(*args, **kwargs)
    self._tmp_dir = None
    self._downloader = None
    # TODO(chuntsen): Move process pool to Instalog core. GCS client instances
    # should be created after multiprocessing.Pool or multiprocessing.Process
    # invokes os.fork(). It may block other plugins with GCS client if we put
    # this line in the SetUp function.
    self._process_pool = multiprocessing.Pool(processes=_PROCESSES_NUMBER)  # pylint: disable=consider-using-with

  def SetUp(self):
    """Sets up the plugin."""
    self._tmp_dir = os.path.join(self.GetDataDir(), 'tmp')
    self._downloader = gcs_utils.ParallelDownloader(logger=self.logger)

  def TearDown(self):
    if os.path.exists(self._tmp_dir):
      shutil.rmtree(self._tmp_dir)

    self._process_pool.close()
    self._process_pool.join()

    self._downloader.Close()

  def Main(self):
    """Main thread of the plugin."""
    if not yaml.__with_libyaml__:
      self.info('Please install LibYAML to speed up this plugin.')
    while not self.IsStopping():
      if not self.DownloadAndProcess():
        self.Sleep(1)

  def DownloadAndProcess(self):
    """Download Archive file from GCS and process it."""
    event_stream = self.NewStream()
    if not event_stream:
      return False

    if os.path.exists(self._tmp_dir):
      shutil.rmtree(self._tmp_dir)
    file_utils.TryMakeDirs(self._tmp_dir)

    total_archive_size = 0
    event_dict = {}
    download_list = []
    for event in event_stream.iter(count=_PROCESSES_NUMBER):
      archive_process_event = datatypes.Event({
          '__process__': True,
          'status': [],
          'time': 0,  # The partitioned table on BigQuery need this field.
          'startTime': 0,
          'message': []
      })
      for key in ('objectId', 'time', 'size', 'md5'):
        if key not in event:
          SetProcessEventStatus(ERROR_CODE.EventInvalid, archive_process_event,
                                event.Serialize())
          self.PreEmit([archive_process_event])
          self.error('Receive an invalid event: %s', event.Serialize())
          continue

      gcs_path = event['objectId']
      archive_extension = os.path.splitext(gcs_path)[1]
      archive_path = os.path.join(
          self._tmp_dir,
          'archive_%d_%s%s' % (event['time'], event['md5'], archive_extension))
      download_list.append((gcs_path, archive_path))

      event['archive_path'] = archive_path
      event['archive_process_event'] = archive_process_event
      event_dict[event['objectId']] = event

      total_archive_size += event['size']
      if total_archive_size >= self.args.archive_batch_size:
        break

    downloader_results = self._downloader.Download(download_list)

    for gcs_path, archive_path in downloader_results:
      event = event_dict[gcs_path]
      archive_process_event = event['archive_process_event']
      archive_process_event['uuid'] = gcs_path
      archive_process_event['startTime'] = time.time()

      # If the downloader failed to download a file, the archive_path will be
      # None.
      if not archive_path:
        self.error('Download failed and skip the archive: %s', gcs_path)
        SetProcessEventStatus(ERROR_CODE.DownloadError, archive_process_event)
        self.PreEmit([archive_process_event])
        continue

      assert archive_path == event['archive_path']

      self.info('Download succeed and start processing: %s', gcs_path)
      report_parsers = []
      try:
        report_parsers = self._CreateReportParsers(gcs_path, archive_path,
                                                   self._tmp_dir)
      except NotImplementedError:
        SetProcessEventStatus(ERROR_CODE.ArchiveInvalidFormat,
                              archive_process_event)
      except Exception as e:
        self.exception('Exception encountered when creating report parsers')
        SetProcessEventStatus(ERROR_CODE.ArchiveUnknownError,
                              archive_process_event, e)
      else:
        if not report_parsers:
          SetProcessEventStatus(ERROR_CODE.ArchiveReportNotFound,
                                archive_process_event)
        else:
          for report_parser in report_parsers:
            total_reports = report_parser.ProcessArchive(
                archive_process_event, self._process_pool, self.PreEmit)
            self.info('Parsed %d reports from %s (size=%d)', total_reports,
                      gcs_path, event['size'])
      self.PreEmit([archive_process_event])

    self.info('Emit events to buffer.')
    if self.Emit([]):
      event_stream.Commit()
    else:
      event_stream.Abort()
    return True

  def _CreateReportParsers(self, gcs_path, archive_path, tmp_dir):
    with GetArchive(archive_path) as archive:
      archives_in_archive = []
      for name in archive.GetNonDirFileNames():
        # Valid report name found, assume this archive is an one-level archive.
        if ReportParser.IsValidReportName(name):
          return [
              ReportParser(gcs_path, archive_path, tmp_dir, '', self.logger)
          ]
        archives_in_archive.append(name)

      # Assume it is a two-level archive, decompress and check every archive
      # files under this archive, see b/225278303.
      report_parsers = []
      for name in archives_in_archive:
        dst = file_utils.CreateTemporaryFile(dir=self._tmp_dir)
        try:
          archive.Extract(name, dst)
        except ExtractError:
          continue

        try:
          GetArchive(dst)
        except NotImplementedError:
          # Extracted file is not a supported archive, clean up and skip.
          os.remove(dst)
          continue
        # Adds a string '(archive) ' as prefix for the archive path to help us
        # distinguish the archive is retrieved from a two-level archive in the
        # output event.
        archive_prefix = '(archive) ' + name
        report_parsers.append(
            ReportParser(gcs_path, dst, tmp_dir, archive_prefix, self.logger))
      # Remove the two-level archive as every one-level archive is handled by
      # each report parser.
      os.remove(archive_path)
      return report_parsers


class HWIDNotFoundInFactoryLogError(Exception):
  pass


class ReportParser(log_utils.LoggerMixin):
  """A parser to process report archives."""

  def __init__(self, gcs_path, archive_path, tmp_dir, report_path_parent_dir,
               logger=logging):
    """Sets up the parser.

    Args:
      gcs_path: Path to the archive on Google Cloud Storage.
      archive_path: Path to the archive on disk.
      tmp_dir: Temporary directory.
      report_path_parent_dir: String value of parent dir to add to every parsed
        report in report events.
      logger: Logger to use.
    """
    self._archive_path = archive_path
    self._tmp_dir = tmp_dir
    self._gcs_path = gcs_path
    self._report_path_parent_dir = report_path_parent_dir
    self.logger = logger

  def ProcessArchive(self, archive_process_event, process_pool,
                     processed_callback):
    """Processes the archive and remove it after processing it."""
    processed = 0
    report_num_by_external_tool = None
    args_queue = multiprocessing.Queue()
    result_queue = multiprocessing.Manager().Queue()
    total_reports = 0
    decompress_process = None

    try:
      # TODO(chuntsen): Find a way to stop process pool.
      if zipfile.is_zipfile(self._archive_path):
        decompress_process = multiprocessing.Process(
            target=self.DecompressZipArchive, args=(args_queue, ))
        report_num_by_external_tool = self._GetReportNumInZip(
            self._archive_path)
      elif tarfile.is_tarfile(self._archive_path):
        decompress_process = multiprocessing.Process(
            target=self.DecompressTarArchive, args=(args_queue, ))
        report_num_by_external_tool = self._GetReportNumInTar(
            self._archive_path)
      else:
        # We only support tar file and zip file.
        SetProcessEventStatus(ERROR_CODE.ArchiveInvalidFormat,
                              archive_process_event)
        return total_reports
      decompress_process.start()

      received_obj = args_queue.get()
      # End the process when we receive None or exception.
      while not (received_obj is None or isinstance(received_obj, Exception)):
        process_report_args = received_obj + (result_queue, )
        process_pool.apply_async(self.ProcessReport, process_report_args)
        total_reports += 1
        received_obj = args_queue.get()

      decompress_process.join()
      decompress_process.close()
      args_queue.close()
      archive_process_event['decompressEndTime'] = time.time()
      if isinstance(received_obj, Exception):
        SetProcessEventStatus(ERROR_CODE.ArchiveUnknownError,
                              archive_process_event, received_obj)

      for unused_i in range(total_reports):
        # TODO(chuntsen): Find a way to stop process pool.
        report_event, process_event = result_queue.get()

        report_time = report_event['time']
        if (archive_process_event['time'] == 0 or
            0 < report_time < archive_process_event['time']):
          archive_process_event['time'] = report_time
        processed += 1
        if processed % 1000 == 0:
          self.info('Parsed %d/%d reports', processed, total_reports)
        processed_callback([report_event, process_event])

      self.info('Parsed %d/%d reports', processed, total_reports)
      if report_num_by_external_tool is None:
        error_msg = 'Cannot check processed report number due to not getting '\
                    'the number with external tool'
        self.error(error_msg)
        SetProcessEventStatus(ERROR_CODE.ArchiveReportNumNotMatch,
                              archive_process_event, error_msg)
      elif report_num_by_external_tool != processed:
        error_msg = f'Processed report number ({processed}) does not match to '\
          f'the one reported by external tool ({report_num_by_external_tool})!'
        self.error(error_msg)
        SetProcessEventStatus(ERROR_CODE.ArchiveReportNumNotMatch,
                              archive_process_event, error_msg)
    except Exception:
      self.exception('Exception encountered')

    archive_process_event['endTime'] = time.time()
    archive_process_event['duration'] = (
        archive_process_event['endTime'] - archive_process_event['startTime'])

    os.remove(self._archive_path)
    return total_reports

  def DecompressZipArchive(self, args_queue):
    """Decompresses the ZIP format archive.

    Args:
      args_queue: Process shared queue to send messages.  A message can be
                  arguments for ProcessReport(), exception or None.
    """
    try:
      with zipfile.ZipFile(self._archive_path, 'r') as archive_obj:
        for member_name in archive_obj.namelist():
          if not self.IsValidReportName(member_name):
            continue

          report_path = file_utils.CreateTemporaryFile(dir=self._tmp_dir)
          with open(report_path, 'wb') as dst_f:
            with archive_obj.open(member_name, 'r') as report_obj:
              shutil.copyfileobj(report_obj, dst_f)
          args_queue.put((member_name, report_path))
    except Exception as e:
      self.exception('Exception encountered when decompressing archive file')
      args_queue.put(e)
    else:
      args_queue.put(None)

  def DecompressTarArchive(self, args_queue):
    """Decompresses the tar archive with compression.

    Args:
      args_queue: Process shared queue to send messages.  A message can be
                  arguments for ProcessReport(), exception or None.
    """
    try:
      # The 'r|*' mode will process data as a stream of blocks, and it may
      # faster than normal 'r:*' mode.
      with tarfile.open(self._archive_path, 'r|*') as archive_obj:
        for archive_member in archive_obj:
          # Some ReportArchives contain symlink, and it is not allow by using
          # 'r|*' mode.
          if archive_member.type != tarfile.REGTYPE:
            continue
          member_name = archive_member.name
          if not self.IsValidReportName(member_name):
            continue

          report_path = file_utils.CreateTemporaryFile(dir=self._tmp_dir)
          with open(report_path, 'wb') as dst_f:
            report_obj = archive_obj.extractfile(archive_member)
            shutil.copyfileobj(report_obj, dst_f)
          args_queue.put((member_name, report_path))
    except Exception as e:
      self.exception('Exception encountered when decompressing archive file')
      args_queue.put(e)
    else:
      args_queue.put(None)

  @staticmethod
  def IsValidReportName(name):
    name = os.path.basename(name)
    # Report name format: {stage}{opt_name}-{serial}-{gmtime}.rpt.xz
    if name.endswith('.rpt.xz'):
      return True
    # Report name format: {gmtime}_{serial}.tar.xz
    if name.endswith('.tar.xz'):
      try:
        time.strptime(name.partition('_')[0], '%Y%m%dT%H%M%SZ')
        return True
      except ValueError:
        pass
    return False

  def ProcessReport(self, report_file_path, report_path, result_queue):
    """Processes the factory report.

    The report are processed into (report_event, process_event) and put into the
    result_queue, where:
      report_event: A report event with information in the factory report.
      process_event: A process event with process information.

    Args:
      report_file_path: Path to the factory report in archive.
      report_path: Path to the factory report on disk.
      result_queue: A shared queue to store processed result.
    """
    uuid = time_utils.TimedUUID()
    report_file_path = os.path.join(self._report_path_parent_dir,
                                    report_file_path)
    report_event = datatypes.Event({
        '__report__': True,
        'uuid': uuid,
        'time': 0,  # The partitioned table on BigQuery need this field.
        'objectId': self._gcs_path,
        'reportFilePath': report_file_path,
        'serialNumbers': {}
    })
    process_event = datatypes.Event({
        '__process__': True,
        'uuid': uuid,
        'time': 0,  # The partitioned table on BigQuery need this field.
        'startTime': time.time(),
        'status': [],
        'message': []
    })
    try:
      report_basename = os.path.basename(report_file_path)
      if report_basename.endswith('.tar.xz'):
        # Report name format: {gmtime}_{serial}.tar.xz
        report_time = time.mktime(
            time.strptime(report_basename.partition('_')[0], '%Y%m%dT%H%M%SZ'))
      else:
        # Report name format: {stage}{opt_name}-{serial}-{gmtime}.rpt.xz
        report_time = time.mktime(
            time.strptime(
                report_basename.rpartition('-')[-1], '%Y%m%dT%H%M%SZ.rpt.xz'))
      report_event['time'] = report_time
      process_event['time'] = report_time
      self.DecompressAndParse(report_path, report_event, process_event)
    except Exception as e:
      SetProcessEventStatus(ERROR_CODE.ReportUnknownError, process_event, e)
      self.exception('Exception encountered when processing factory report')
    finally:
      file_utils.TryUnlink(report_path)
    process_event['endTime'] = time.time()
    process_event['duration'] = (
        process_event['endTime'] - process_event['startTime'])
    result_queue.put((report_event, process_event))

  def DecompressAndParse(self, report_path, report_event, process_event):
    """Decompresses the factory report and parse it."""
    with file_utils.TempDirectory(dir=self._tmp_dir) as report_dir:
      if not tarfile.is_tarfile(report_path):
        SetProcessEventStatus(ERROR_CODE.ReportInvalidFormat, process_event)
        return
      with tarfile.open(report_path, 'r|xz') as report_tar:
        report_tar.extractall(report_dir)
      process_event['decompressEndTime'] = time.time()

      eventlog_path = os.path.join(report_dir, 'events')
      if os.path.exists(eventlog_path):
        eventlog_report_event = copy.deepcopy(report_event)
        if self.ParseEventlogEvents(eventlog_path, eventlog_report_event,
                                    process_event):
          report_event.payload = eventlog_report_event.payload
      else:
        SetProcessEventStatus(ERROR_CODE.EventlogFileNotFound, process_event)

      testlog_path = os.path.join(report_dir, 'var', 'factory', 'testlog',
                                  'events.json')
      if os.path.exists(testlog_path):
        testlog_report_event = copy.deepcopy(report_event)
        if self.ParseTestlogEvents(testlog_path, testlog_report_event,
                                   process_event):
          report_event.payload = testlog_report_event.payload
      else:
        SetProcessEventStatus(ERROR_CODE.TestlogFileNotFound, process_event)

      if 'hwid' not in report_event:
        factory_log_path = os.path.join(report_dir, 'var', 'factory', 'log',
                                        'factory.log')
        try:
          extracted_hwid = self._ExtractHWIDFromFactoryLog(factory_log_path)
          report_event['hwid'] = extracted_hwid
          report_event['modelName'] = extracted_hwid.split(' ')[0]
        except FileNotFoundError:
          SetProcessEventStatus(ERROR_CODE.FactorylogFileNotFound,
                                process_event)
        except HWIDNotFoundInFactoryLogError:
          self.warning('HWID not found in factory.log')
          SetProcessEventStatus(ERROR_CODE.FactorylogNoHWID, process_event)

      return

  def ParseEventlogEvents(self, path, report_event, process_event):
    """Parses Eventlog file."""

    def SetSerialNumber(sn_key, sn_value):
      if not isinstance(sn_value, str):
        SetProcessEventStatus(ERROR_CODE.EventlogWrongType, process_event)
        sn_value = str(sn_value)
      if sn_value != 'null':
        report_event['serialNumbers'][sn_key] = sn_value

    def ParseTestStates(test_states, test_states_list):
      if 'subtests' in test_states:
        for subtest in test_states['subtests']:
          ParseTestStates(subtest, test_states_list)
      if 'status' in test_states:
        test_states_list.append((test_states['path'], test_states['status']))

    END_TOKEN = b'---\n'

    try:
      data_lines = b''
      with open(path, 'rb') as fp:
        for line in fp:
          if line != END_TOKEN:
            # If the log file is not sync to disk correctly, it may have null
            # characters. The data after the last null character should be the
            # first line of a new event.
            if b'\0' in line:
              splited_line = line.split(b'\0')
              data_lines += splited_line[0]
              SetProcessEventStatus(ERROR_CODE.EventlogNullCharactersExist,
                                    process_event, data_lines)

              data_lines = splited_line[-1]
            else:
              data_lines += line
          else:
            raw_event = data_lines
            data_lines = b''
            event = None
            try:
              event = yaml.load(raw_event, Loader=yaml_loader)

              if not isinstance(event, dict):
                SetProcessEventStatus(ERROR_CODE.EventlogBrokenEvent,
                                      process_event, raw_event)
                continue

              def GetField(field, dct, key, is_string=True, replace=True):
                if not key in dct:
                  return
                data = dct[key]
                if data == 'null':
                  return

                if is_string and not isinstance(data, str):
                  SetProcessEventStatus(ERROR_CODE.EventlogWrongType,
                                        process_event)
                  data = str(dct[key])

                if field in report_event:
                  if not replace:
                    return
                  if report_event[field] != data:
                    SetProcessEventStatus(
                        ERROR_CODE.EventlogDataChange, process_event,
                        'Field=%s, Old data=%s, New data=%s, Replace=%s' %
                        (field, report_event[field], data, replace))

                report_event[field] = data

              serial_numbers = event.get('serial_numbers', {})
              if not isinstance(serial_numbers, dict):
                SetProcessEventStatus(ERROR_CODE.EventlogWrongType,
                                      process_event)
              else:
                for sn_key, sn_value in serial_numbers.items():
                  SetSerialNumber(sn_key, sn_value)

              event_name = event.get('EVENT', None)
              if event_name == 'system_details':
                crossystem = event.get('crossystem', {})
                # The HWID in crossystem may be incorrect.
                GetField('hwid', crossystem, 'hwid', replace=False)
                if 'hwid' in report_event:
                  report_event['modelName'] = report_event['hwid'].split(' ')[0]
                GetField('fwid', crossystem, 'fwid')
                GetField('roFwid', crossystem, 'ro_fwid')
                GetField('wpswBoot', crossystem, 'wpsw_boot')
                GetField('wpswCur', crossystem, 'wpsw_cur')
                GetField('ecWpDetails', event, 'ec_wp_status')
                if 'ecWpDetails' in report_event:
                  result = PATTERN_WP_STATUS.findall(
                      report_event['ecWpDetails'])
                  if len(result) == 1:
                    report_event['ecWpStatus'] = result[0]
                  result = PATTERN_WP.findall(report_event['ecWpDetails'])
                  if len(result) == 1:
                    report_event['ecWp'] = result[0]
                GetField('biosWpDetails', event, 'bios_wp_status')
                if 'biosWpDetails' in report_event:
                  result = PATTERN_WP_STATUS.findall(
                      report_event['biosWpDetails'])
                  if len(result) == 1:
                    report_event['biosWpStatus'] = result[0]
                  result = PATTERN_WP.findall(report_event['biosWpDetails'])
                  if len(result) == 1:
                    report_event['biosWp'] = result[0]
                GetField('modemStatus', event, 'modem_status')
                GetField('platformName', event, 'platform_name')
              elif event_name in ('write_hwid', 'verified_hwid'):
                GetField('hwid', event, 'hwid')
                if 'hwid' in report_event:
                  report_event['modelName'] = report_event['hwid'].split(' ')[0]
              elif event_name == 'scan':
                for sn_key in ['serial_number', 'mlb_serial_number']:
                  if event.get('key', None) == sn_key and 'value' in event:
                    SetSerialNumber(sn_key, event['value'])
              elif event_name == 'finalize_image_version':
                GetField('factoryImageVersion', event, 'factory_image_version')
                GetField('releaseImageVersion', event, 'release_image_version')
              elif event_name == 'preamble':
                GetField('dutDeviceId', event, 'device_id')
                GetField('toolkitVersion', event, 'toolkit_version')
              elif event_name == 'test_states':
                test_states_list = []
                testlist_name = None
                testlist_station_set = set()

                ParseTestStates(event['test_states'], test_states_list)
                for test_path, unused_test_status in test_states_list:
                  if ':' in test_path:
                    testlist_name, test_path = test_path.split(':')
                  testlist_station = test_path.split('.')[0]
                  testlist_station_set.add(testlist_station)

                report_event['testStates'] = test_states_list
                if testlist_name:
                  report_event['testlistName'] = testlist_name
                report_event['testlistStation'] = json.dumps(
                    list(testlist_station_set))
            except yaml.YAMLError as e:
              SetProcessEventStatus(ERROR_CODE.EventlogBrokenEvent,
                                    process_event, e)
            except Exception as e:
              SetProcessEventStatus(ERROR_CODE.EventlogUnknownError,
                                    process_event, e)

      # There should not have data after the last END_TOKEN.
      if data_lines:
        SetProcessEventStatus(ERROR_CODE.EventlogBrokenEvent, process_event,
                              data_lines)

      # Some reports doesn't have serial_numbers field. However, serial numbers
      # are very important in a report_event, so we try to parse them again.
      content = None
      for sn_key, pattern in [('serial_number', PATTERN_SERIAL_NUMBER),
                              ('mlb_serial_number', PATTERN_MLB_SERIAL_NUMBER)]:
        if sn_key not in report_event['serialNumbers']:
          if not content:
            content = file_utils.ReadFile(path, encoding=None)
          line_list = pattern.findall(content)
          sn_list = []
          for line in line_list:
            try:
              sn = yaml.load(line, Loader=yaml_loader)[sn_key]
              if sn != 'null':
                sn_list.append(sn)
            except Exception:
              pass
          if len(sn_list) > 0:
            # We use the most frequent value.
            sn_value = max(set(sn_list), key=sn_list.count)
            SetSerialNumber(sn_key, sn_value)

      return True
    except Exception as e:
      SetProcessEventStatus(ERROR_CODE.EventlogUnknownError, process_event, e)
      self.exception('Failed to parse eventlog events')
      return False

  def ParseTestlogEvents(self, path, report_event, process_event):
    """Parses Testlog file."""
    try:
      with open(path, 'r', encoding='utf8') as f:
        for line in f:
          # If the log file is not sync to disk correctly, it may have null
          # characters.
          if '\0' in line:
            SetProcessEventStatus(ERROR_CODE.TestlogNullCharactersExist,
                                  process_event)
          # If the log file is not sync to disk correctly, a line may have a
          # broken event and a new event. We can use the EVENT_START to find
          # the new event.
          EVENT_START = '{"payload":'
          new_event_index = line.rfind(EVENT_START)
          if new_event_index > 0:
            SetProcessEventStatus(ERROR_CODE.TestlogBrokenEvent, process_event)
            line = line[new_event_index:]

          try:
            event = datatypes.Event.Deserialize(line)

            if 'serialNumbers' in event:
              for sn_key, sn_value in event['serialNumbers'].items():
                if not isinstance(sn_value, str):
                  SetProcessEventStatus(ERROR_CODE.TestlogWrongType,
                                        process_event)
                  sn_value = str(sn_value)
                report_event['serialNumbers'][sn_key] = sn_value
            if 'time' in event:
              report_event['dutTime'] = event['time']

            for field in REPORT_EVENT_FIELD:
              if field in event:
                report_event[field] = event[field]

            def GetField(field, event, key, replace=True):
              data_list = event.get('parameters', {}).get(key, {}).get(
                  'data', [])
              if len(data_list) != 1:
                return

              data = None
              for data_type in ['numericValue', 'textValue', 'serializedValue']:
                if data_type in data_list[0]:
                  data = data_list[0][data_type]
              if data is None:
                return
              if field in report_event:
                if not replace:
                  return
                if report_event[field] != data:
                  SetProcessEventStatus(
                      ERROR_CODE.TestlogDataChange, process_event,
                      'Field=%s, Old data=%s, New data=%s, Replace=%s' %
                      (field, report_event[field], data, replace))
              report_event[field] = data

            if event.get('testType', None) == 'hwid':
              GetField('phase', event, 'phase')
              GetField('hwid', event, 'verified_hwid')
              if 'hwid' in report_event:
                report_event['modelName'] = report_event['hwid'].split(' ')[0]
          except json.JSONDecodeError as e:
            SetProcessEventStatus(ERROR_CODE.TestlogBrokenEvent, process_event,
                                  e)
          except Exception as e:
            SetProcessEventStatus(ERROR_CODE.TestlogUnknownError, process_event,
                                  e)
      return True
    except Exception as e:
      SetProcessEventStatus(ERROR_CODE.TestlogUnknownError, process_event, e)
      self.exception('Failed to parse testlog events')
      return False

  def _ExtractHWIDFromFactoryLog(self, log_path):
    """Extracts and returns a HWID string from the given factory.log."""
    hwid_candidate = ''
    with open(log_path, 'r', encoding='utf8') as f:
      for line in f:
        match_result = PATTERN_HWID_LOG.match(line)
        if match_result is not None:
          hwid_candidate = match_result.group('hwid')
    if hwid_candidate:
      return hwid_candidate
    raise HWIDNotFoundInFactoryLogError

  def _GetReportNumInZip(self, zip_path):
    """Returns the number of factory report in the zip archive via `unzip -l`.

    Args:
      zip_path: the string path of the zip archive.
    Returns:
      A non-negative number, or None if encounter exception.
    """
    try:
      output = process_utils.CheckOutput(['unzip', '-l', zip_path])
      lines = output.split('\n')
      return sum(map(lambda line: self.IsValidReportName(line.strip()), lines))
    except Exception:
      self.exception('Cannot get number of reports in %s', zip_path)
      return None

  def _GetReportNumInTar(self, tar_path):
    """Returns the number of factory report in the archive via `tar tvf`.

    Args:
      tar_path: the string path of the tar archive.
    Returns:
      A non-negative number, or None if encounter exception.
    """
    try:
      output = process_utils.CheckOutput(['tar', 'tvf', tar_path])
      lines = output.split('\n')
      return sum(map(lambda line: self.IsValidReportName(line.strip()), lines))
    except Exception:
      self.exception('Cannot get number of reports in %s', tar_path)
      return None


ERROR_CODE = type_utils.Obj(
    EventInvalid=100,
    DownloadError=101,
    ArchiveInvalidFormat=200,
    ArchiveReportNumNotMatch=201,
    ArchiveReportNotFound=202,
    ArchiveUnknownError=299,
    ReportInvalidFormat=300,
    ReportUnknownError=399,
    EventlogFileNotFound=400,
    EventlogNullCharactersExist=401,
    EventlogWrongType=402,
    EventlogBrokenEvent=403,
    EventlogDataChange=404,
    EventlogUnknownError=499,
    TestlogFileNotFound=500,
    TestlogNullCharactersExist=501,
    TestlogWrongType=502,
    TestlogBrokenEvent=503,
    TestlogDataChange=504,
    TestlogUnknownError=599,
    FactorylogFileNotFound=600,
    FactorylogNoHWID=601,
    FactorylogUnknownError=699,
)


def SetProcessEventStatus(code, process_event, message=None):
  """Sets status and message to process_event.

  See ERROR_CODE and http://b/184819627 (Googlers only) for details.
  Error Code type:
    1xx Event Error:
    2xx Archive Error:
    3xx Report Error:
    4xx Eventlog Error:
    5xx Testlog Error:
    6xx Other Error:
  """
  if code not in process_event['status']:
    process_event['status'].append(code)
  if isinstance(message, str):
    process_event['message'].append(message)
  elif isinstance(message, bytes):
    try:
      process_event['message'].append(message.decode('utf-8'))
    except UnicodeDecodeError:
      pass
  elif message:
    process_event['message'].append(str(message))
    if isinstance(message, Exception):
      process_event['message'].append(traceback.format_exc())


class ExtractError(Exception):
  """Generic error if extracting archive content failed."""


class Archive(abc.ABC):

  def __init__(self, archive_path):
    self._archive_path = archive_path
    self._file = None

  def __enter__(self):
    self._OpenArchive()
    return self

  def __exit__(self, exc_type, exc_value, exit_traceback):
    self._CloseArchive()

  @abc.abstractmethod
  def GetNonDirFileNames(self):
    """Get a list of all non-directory file path names in the archive.

    Returns:
      A list of string file path names.
    """
    raise NotImplementedError

  @abc.abstractmethod
  def Extract(self, member_name, dst_path):
    """Extract a member in the archive to a specified path.

    Args:
      member_name: The string full path name of the target file to extract.
      dst_path: A string path where the extracted file should store to.
    """
    raise NotImplementedError

  @abc.abstractmethod
  def _OpenArchive(self):
    raise NotImplementedError

  def _CloseArchive(self):
    self._file.close()


class ZipArchive(Archive):

  def GetNonDirFileNames(self):
    return [
        info.filename for info in self._file.infolist() if not info.is_dir()
    ]

  def Extract(self, member_name, dst_path):
    with self._file.open(member_name, 'r') as member, \
         open(dst_path, 'wb') as dst_file:
      shutil.copyfileobj(member, dst_file)

  def _OpenArchive(self):
    self._file = zipfile.ZipFile(self._archive_path, 'r')  # pylint: disable=consider-using-with


class ZipWith7ZArchive(Archive):

  def __init__(self, archive_path):
    super().__init__(archive_path)
    self._non_dir_files_in_archive = []

  def GetNonDirFileNames(self):
    return self._non_dir_files_in_archive

  def Extract(self, member_name, dst_path):
    with file_utils.TempDirectory() as tmp_dir:
      process_utils.Spawn(
          ['7z', 'x', self._archive_path, member_name, f'-o{tmp_dir}'],
          stdout=subprocess.DEVNULL, call=True)
      try:
        shutil.move(os.path.join(tmp_dir, member_name), dst_path)
      except FileNotFoundError as e:
        raise ExtractError from e

  def _OpenArchive(self):
    output = process_utils.SpawnOutput(
        ['7z', 'l', '-slt', '-ba', self._archive_path])
    # The -slt (technical information list format) output is composed by
    # sections, each section is either a file or a directory
    # The output format of a section is:
    #   Path = <file path>\n
    #   ...
    #   Attributes = <file attributes>\n
    #   ...
    #   \n
    section_regex = re.compile(
        r'Path = (?P<file_path>.+?\n)(?:.*?\n)*?' +
        r'Attributes = (?P<attributes>.*?\n)(?:.*?\n)*?\n', re.DOTALL)
    for match in section_regex.finditer(output):
      file_path = match.group('file_path').strip()
      attributes = match.group('attributes').strip()
      if 'D' not in attributes:
        self._non_dir_files_in_archive.append(file_path)

  def _CloseArchive(self):
    """7z archive does not open any file, thus no need to clean up."""


class TarArchive(Archive):

  def GetNonDirFileNames(self):
    return [
        member.name for member in self._file.getmembers() if not member.isdir()
    ]

  def Extract(self, member_name, dst_path):
    with self._file.extractfile(member_name) as member, \
         open(dst_path, 'wb') as dst_file:
      shutil.copyfileobj(member, dst_file)

  def _OpenArchive(self):
    self._file = tarfile.open(self._archive_path, 'r')  # pylint: disable=consider-using-with


def GetArchive(archive_path):
  # It is better to handle as much archive as possible, so we first try with the
  # `zipfile` package, then use `7z` as fallback.
  if zipfile.is_zipfile(archive_path):
    return ZipArchive(archive_path)
  if archive_path.endswith('.zip'):
    return ZipWith7ZArchive(archive_path)
  if tarfile.is_tarfile(archive_path):
    return TarArchive(archive_path)
  raise NotImplementedError


if __name__ == '__main__':
  plugin_base.main()
