# Copyright (c) 2012 The Chromium OS Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.


"""The package initialization and abstract base class for shop floor systems.

Every implementations should inherit ShopFloorBase and override the member
functions to interact with their real shop floor system.
"""

import csv
import glob
import logging
import os
import shutil
import time
import xmlrpclib

# In current implementation, we use xmlrpclib.Binary to prepare blobs.
from xmlrpclib import Binary

import factory_common
from cros.factory.shopfloor import factory_update_server, factory_log_server
from cros.factory.test import factory
from cros.factory.test import shopfloor
from cros.factory.test import utils
from cros.factory.test.registration_codes import CheckRegistrationCode
from cros.factory.utils.process_utils import Spawn


EVENTS_DIR = 'events'
INCREMENTAL_EVENTS_DIR = 'events_incremental'
REPORTS_DIR = 'reports'
AUX_LOGS_DIR = 'aux_logs'
UPDATE_DIR = 'update'
PARAMETERS_DIR = 'parameters'
FACTORY_LOG_DIR = 'system_logs'
REGISTRATION_CODE_LOG_CSV = 'registration_code_log.csv'
LOGS_DIR_FORMAT = 'logs.%Y%m%d'
HOURLY_DIR_FORMAT = 'logs.%Y%m%d-%H'

IN_PROGRESS_SUFFIX = '.INPROGRESS'

class NewlineTerminatedCSVDialect(csv.excel):
  lineterminator = '\n'


class ShopFloorException(Exception):
  pass


class ShopFloorBase(object):
  """Base class for shopfloor servers.

  Properties:
    config: The configuration data provided by the '-c' argument to
      shopfloor_server.
    data_dir: The top-level directory for shopfloor data.
    update_server: An FactoryUpdateServer for factory environment update.
    log_server: An FactoryLogServer for factory log files to be uploaded
      from dut.
    _auto_archive_logs: An optional path to use for auto-archiving
      logs (see the --auto-archive-logs command-line argument).  This
      must contain the string 'DATE'.
    _auto_archive_logs_days: Number of days of logs to save.
    _auto_archive_logs_dir_exists: True if the parent of _auto_archive_logs
      existed the last time we checked, False if not, or None if we've
      never checked.
  """

  NAME = 'ShopFloorBase'
  VERSION = 4

  def __init__(self):
    self.data_dir = None  # Set by shopfloor_server
    self.update_dir = None
    self.parameters_dir = None
    self.update_server = None
    self.factory_log_dir = None
    self.log_server = None
    self.events_rotate_hourly = False
    self.reports_rotate_hourly = False
    self._auto_archive_logs = None
    self._auto_archive_logs_days = None
    self._auto_archive_logs_dir_exists = None

  def _InitBase(self, auto_archive_logs, auto_archive_logs_days, updater=None):
    """Initializes the base class.

    Args:
      auto_archive_logs: See _auto_archive_logs property.
      updater: A reference to factory updater. Factory updater provides
               interfaces compatible to FactoryUpdateServer. Including
               Start, Stop, hwid_path, GetTestMD5, NeedsUpdate and rsync_port.
    """
    if auto_archive_logs_days > 0 and auto_archive_logs:
      assert 'DATE' in auto_archive_logs, (
          '--auto-archive-logs flag must contain the string DATE')
      self._auto_archive_logs = auto_archive_logs
      self._auto_archive_logs_days = auto_archive_logs_days

    if not os.path.exists(self.data_dir):
      logging.warn('Data directory %s does not exist; creating it',
                   self.data_dir)
      os.makedirs(self.data_dir)

    if updater is None:
      # Dynamic test directory for holding updates is called "update" in
      # data_dir.
      self.update_dir = os.path.join(self.data_dir, UPDATE_DIR)
      utils.TryMakeDirs(self.update_dir)
      self.update_dir = os.path.realpath(self.update_dir)
      self.update_server = factory_update_server.FactoryUpdateServer(
          self.update_dir,
          on_idle=(self._AutoSaveLogs if self._auto_archive_logs else None))
      # Create factory log directory
      self.factory_log_dir = os.path.join(self.data_dir, FACTORY_LOG_DIR)
      utils.TryMakeDirs(self.factory_log_dir)
      self.factory_log_dir = os.path.realpath(self.factory_log_dir)
      self.log_server = factory_log_server.FactoryLogServer(
          self.factory_log_dir)
    else:
      # Use external update server and log server
      self.update_server = updater
      self.log_server = updater
      # When using external updater, events and reports rotate hourly
      # TODO(rongchang): modify internal auto log archive
      self.reports_rotate_hourly = True
      self.events_rotate_hourly = True
    # Create parameters directory
    self.parameters_dir = os.path.join(self.data_dir, PARAMETERS_DIR)
    utils.TryMakeDirs(self.parameters_dir)
    self.parameters_dir = os.path.realpath(self.parameters_dir)

  def _StartBase(self):
    """Starts the base class."""
    if self.update_server:
      logging.debug('Starting factory update server...')
      self.update_server.Start()
    logging.debug('Starting factory log server...')
    self.log_server.Start()

  def _StopBase(self):
    """Stops the base class."""
    if self.update_server:
      self.update_server.Stop()
    self.log_server.Stop()

  def _AutoSaveLogs(self):
    """Implements functionality to automatically save logs to USB.

    (See the description of the --auto-archive-logs command-line argument
    for details.)
    """
    auto_archive_dir = os.path.dirname(self._auto_archive_logs)
    new_auto_archive_logs_dir_exists = os.path.isdir(auto_archive_dir)
    if new_auto_archive_logs_dir_exists != self._auto_archive_logs_dir_exists:
      # If the auto-archive directory is newly present (or not present),
      # log a message.
      if new_auto_archive_logs_dir_exists:
        logging.info("Auto-archive directory %s found; will auto-archive "
                     "past %d days' logs there if not present",
                     auto_archive_dir, self._auto_archive_logs_days)
      else:
        logging.info("Auto-archive directory %s not found; create it (or mount "
                     "media there) to auto-archive past %d days' logs",
                     auto_archive_dir, self._auto_archive_logs_days)
      self._auto_archive_logs_dir_exists = new_auto_archive_logs_dir_exists

    if new_auto_archive_logs_dir_exists:
      for days_ago in xrange(1, self._auto_archive_logs_days + 1):
        past_day = time.localtime(time.time() - days_ago * 86400)
        past_day_logs_dir_name = time.strftime(LOGS_DIR_FORMAT, past_day)
        archive_name = os.path.join(
            self._auto_archive_logs.replace(
                'DATE', time.strftime('%Y%m%d', past_day)))
        if os.path.exists(archive_name):
          # We've already done this.
          continue

        past_day_logs_dir = os.path.join(self.data_dir, REPORTS_DIR,
                                         past_day_logs_dir_name)
        if not os.path.exists(past_day_logs_dir):
          # There aren't any logs from past_day.
          continue

        in_progress_name = archive_name + IN_PROGRESS_SUFFIX
        logging.info('Archiving %s to %s', past_day_logs_dir, archive_name)

        have_pbzip2 = Spawn(
            ['which', 'pbzip2'],
            ignore_stdout=True, ignore_stderr=True, call=True).returncode == 0

        Spawn(['tar', '-I', 'pbzip2' if have_pbzip2 else 'bzip2',
               '-cf', in_progress_name,
               '-C', os.path.join(self.data_dir, REPORTS_DIR),
               past_day_logs_dir_name],
              check_call=True, log=True, log_stderr_on_error=True)
        shutil.move(in_progress_name, archive_name)
        logging.info('Finishing archiving %s to %s',
                     past_day_logs_dir, archive_name)

  def SaveReport(self, report_name, report_blob):
    """Saves a report to disk and checks its integrity.

    Args:
      report_path: Name of the report.
      report_blob: Contents of the report.

    Raises:
      ShopFloorException on error.
    """
    report_path = os.path.join(self.GetReportsDir(), report_name)
    in_progress_path = report_path + IN_PROGRESS_SUFFIX
    try:
      with open(in_progress_path, "wb") as f:
        f.write(report_blob)
      self.CheckReportIntegrity(in_progress_path)
      shutil.move(in_progress_path, report_path)
    finally:
      try:
        # Attempt to remove the in-progress file (e.g., if the
        # integrity check failed)
        os.unlink(in_progress_path)
      except OSError:
        pass

  def CheckReportIntegrity(self, report_path):
    """Checks the integrity of a report.

    This checks to make sure that "tar tf" on the report does not return any
    errors, and that the report contains var/factory/log/factory.log.

    Raises:
      ShopFloorException on error.
    """
    process = Spawn(['tar', '-tf', report_path], log=True,
                     read_stdout=True, read_stderr=True)

    if process.returncode:
      error = 'Corrupt report: tar failed'
    elif (factory.FACTORY_LOG_PATH_ON_DEVICE.lstrip('/') not in
          process.stdout_data.split('\n')):
      error = 'Corrupt report: %s missing' % (
          factory.FACTORY_LOG_PATH_ON_DEVICE.lstrip('/'))
    else:
      # OK!  Save the MD5SUM (removing the INPROGRESS suffix if any)
      # and return.
      md5_path = report_path
      if report_path.endswith(IN_PROGRESS_SUFFIX):
        md5_path = md5_path[:-len(IN_PROGRESS_SUFFIX)]
      md5_path += '.md5'
      try:
        with open(md5_path, 'w') as f:
          Spawn(['md5sum', report_path], stdout=f, check_call=True)
      except:
        try:
          os.unlink(md5_path)
        except OSError:
          pass
        raise
      return

    error += ': tar returncode=%d, stderr=%r' % (
        process.returncode, process.stderr_data)
    logging.error(error)
    raise ShopFloorException(error)


  def GetLogsDir(self, subdir=None, log_format=LOGS_DIR_FORMAT):
    """Returns the active logs directory.

    This is the data directory base plus a path element 'subdir'. When
    log_format is not None, it creates one more level of log folder to
    rotate the logs. Default log_format is "logs.YYMMDD", where YYMMDD
    is today's date in the local time zone.  This creates the directory
    if it does not exist.

    Args:
      subdir: If not None, this is appended to the path.
      log_format: strftime log format for log rotation.
    """
    ret = self.data_dir
    if subdir:
      ret = os.path.join(ret, subdir)
      utils.TryMakeDirs(ret)
    if log_format:
      ret = os.path.join(ret, time.strftime(log_format))
      utils.TryMakeDirs(ret)
    return ret

  def SetEventHourlyRotation(self, value):
    """Enables the option for additional hourly rotation of events."""
    self.events_rotate_hourly = value
    return self.events_rotate_hourly

  def SetReportHourlyRotation(self, value):
    """Enables the option for hourly rotation of reports."""
    self.reports_rotate_hourly = value
    return self.reports_rotate_hourly

  def GetEventsDir(self):
    """Returns the active events directory."""
    return self.GetLogsDir(EVENTS_DIR, log_format=None)

  def GetIncrementalEventsDir(self):
    """Returns the active incremental events directory."""
    return self.GetLogsDir(INCREMENTAL_EVENTS_DIR, log_format=HOURLY_DIR_FORMAT)

  def GetReportsDir(self):
    """Returns the active reports directory."""
    if self.reports_rotate_hourly:
      return self.GetLogsDir(REPORTS_DIR, log_format=HOURLY_DIR_FORMAT)
    return self.GetLogsDir(REPORTS_DIR)

  def GetAuxLogsDir(self):
    """Returns the active auxiliary logs directory."""
    return self.GetLogsDir(AUX_LOGS_DIR)

  def Init(self):
    """Initializes the shop floor system.

    Subclasses should implement this rather than __init__.
    """
    pass

  def Ping(self):
    """Always returns true (for client to check if server is working)."""
    return True

  def CheckSN(self, serial):
    """Checks whether a serial number is valid.

    Args:
      serial: A string of device serial number.

    Returns:
      True if the serial number provided is considered valid.

    Raises:
      ValueError if serial is invalid, or other exceptions defined by individual
      modules. Note this will be converted to xmlrpclib.Fault when being used as
      a XML-RPC server module.
    """
    raise NotImplementedError('CheckSN')

  def ListParameters(self, pattern):
    """Lists files that match the pattern in parameters directory.

     Args:
       pattern: A pattern string for glob to list matched files.

     Returns:
       A list of matched files.

     Raises:
       ValueError if caller is trying to query outside parameters directory.
    """
    glob_pathname = os.path.abspath(os.path.join(self.parameters_dir, pattern))
    if not glob_pathname.startswith(self.parameters_dir):
      raise ValueError('ListParameters is limited to parameter directory')

    matched_file = glob.glob(glob_pathname)
    # Only return files.
    matched_file = filter(os.path.isfile, matched_file)
    return [os.path.relpath(x, self.parameters_dir) for x in matched_file]

  # TODO(itspeter): Implement DownloadParameter.
  def GetParameter(self, path):
    """Gets the assigned parameter file.

     Args:
       path: A relative path for locating the parameter.

     Returns:
       Content of the parameter. It is always wrapped in a shopfloor.Binary
       object to provides best flexibility.

     Raises:
       ValueError if the parameter does not exist or is not under
       parameters folder.
    """
    abspath = os.path.abspath(os.path.join(self.parameters_dir, path))
    if not abspath.startswith(self.parameters_dir):
      raise ValueError('GetParameter is limited to parameter directory')

    if not os.path.isfile(abspath):
      raise ValueError('File does not exist or it is not a file')

    return Binary(open(abspath).read())

  def GetHWID(self, serial):
    """Returns appropriate HWID according to given serial number.

    Args:
      serial: A string of device serial number.

    Returns:
      The associated HWID string.

    Raises:
      ValueError if serial is invalid, or other exceptions defined by individual
      modules. Note this will be converted to xmlrpclib.Fault when being used as
      a XML-RPC server module.
    """
    raise NotImplementedError('GetHWID')

  def GetHWIDUpdater(self):
    """Returns a HWID updater bundle, if available.

    Returns:
      The binary-encoded contents of a file named 'hwid_*' in the data
      directory.  If there are no such files, returns None.

    Raises:
      ShopFloorException if there are >1 HWID bundles available.
    """
    path = self.update_server.hwid_path
    return Binary(open(path).read()) if path else None

  def GetVPD(self, serial):
    """Returns VPD data to set (in dictionary format).

    Args:
      serial: A string of device serial number.

    Returns:
      VPD data in dict {'ro': dict(), 'rw': dict()}

    Raises:
      ValueError if serial is invalid, or other exceptions defined by individual
      modules. Note this will be converted to xmlrpclib.Fault when being used as
      a XML-RPC server module.
    """
    raise NotImplementedError('GetVPD')

  def UploadReport(self, serial, report_blob, report_name=None):
    """Uploads a report file.

    Args:
      serial: A string of device serial number.
      report_blob: Blob of compressed report to be stored (must be prepared by
          shopfloor.Binary)
      report_name: (Optional) Suggested report file name. This is uslally
          assigned by factory test client programs (ex, gooftool); however
          server implementations still may use other names to store the report.

    Returns:
      True on success.

    Raises:
      ValueError if serial is invalid, or other exceptions defined by individual
      modules. Note this will be converted to xmlrpclib.Fault when being used as
      a XML-RPC server module.
    """
    raise NotImplementedError('UploadReport')

  def SaveAuxLog(self, name, contents):
    """Saves an auxiliary log into the logs.$(DATE)/aux_logs directory.

    In general, this should probably be compressed to save space.

    Args:
      name: Name of the report.  Any existing log with the same name will be
        overwritten.  Subdirectories are allowed.
      contents: Contents of the report.  If this is binary, it should be
        wrapped in a shopfloor.Binary object.
    """
    contents = self.UnwrapBlob(contents)

    # Disallow absolute paths and paths with '..'.
    assert not os.path.isabs(name)
    assert '..' not in os.path.split(name)

    path = os.path.join(self.GetAuxLogsDir(), name)
    utils.TryMakeDirs(os.path.dirname(path))
    with open(path, "wb") as f:
      f.write(contents)

  def Finalize(self, serial):
    """Marks target device (by serial) to be ready for shipment.

    Args:
      serial: A string of device serial number.

    Returns:
      True on success.

    Raises:
      ValueError if serial is invalid, or other exceptions defined by individual
      modules. Note this will be converted to xmlrpclib.Fault when being used as
      a XML-RPC server module.
    """
    raise NotImplementedError('Finalize')

  def GetRegistrationCodeMap(self, serial):
    """Returns the registration code map for the given serial number.

    Returns:
      {'user': registration_code, 'group': group_code}

    Raises:
      ValueError if serial is invalid, or other exceptions defined by individual
      modules. Note this will be converted to xmlrpclib.Fault when being used as
      a XML-RPC server module.
    """
    raise NotImplementedError('GetRegistrationCode')

  def GetAuxData(self, table_name, id):  # pylint: disable=W0622
    """Returns a row from an auxiliary table.

    Args:
      table_name: The table containing the desired row.
      id: The ID of the row to return.

    Returns:
      A map of properties from the given table.

    Raises:
      ValueError if the ID cannot be found in the table.  Note this will be
      converted to xmlrpclib.Fault when being used as an XML-RPC server
      module.
    """
    raise NotImplementedError('GetAuxData')

  def LogRegistrationCodeMap(self, registration_code_map,
                             log_filename='registration_code_log.csv',
                             board=None, hwid=None):
    """Logs that a particular registration code has been used.
    Args:
      registration_code_map: A dict contains 'user' and 'group' reg code.
      log_filename: File to append log to.
      board: Board name. If None, will try to derive it from hwid.
      hwid: HWID object, could be None.

    Raises:
      ValueError if the registration code is invalid.
      ValueError if both board and hwid are None.
    """
    for key in ('user', 'group'):
      CheckRegistrationCode(registration_code_map[key])

    if not board:
      if hwid:
        board = hwid.partition(' ')[0]
      else:
        raise ValueError('Both board and hwid are missing.')

    if not hwid:
      hwid = ''

    # See http://goto/nkjyr for file format.
    with open(os.path.join(self.data_dir, log_filename), "ab") as f:
      csv.writer(f, dialect=NewlineTerminatedCSVDialect).writerow([
        board,
        registration_code_map['user'],
        registration_code_map['group'],
        time.strftime("%Y-%m-%d %H:%M:%S", time.gmtime()),
        hwid])
      os.fdatasync(f.fileno())

  def GetFactoryLogPort(self):
    """Returns the port to use for rsync factory logs.

    Returns:
      The port, or None if there is no factory log server available.
    """
    return self.log_server.rsyncd_port if self.log_server else None

  def GetTestMd5sum(self):
    """Gets the latest md5sum of dynamic test tarball.

    Returns:
      A string of md5sum.  None if no dynamic test tarball is installed.
    """
    return self.update_server.GetTestMd5sum()

  def NeedsUpdate(self, device_md5sum):
    """Checks if the device with device_md5sum needs an update."""
    return self.update_server.NeedsUpdate(device_md5sum)

  def GetUpdatePort(self):
    """Returns the port to use for rsync updates.

    Returns:
      The port, or None if there is no update server available.
    """
    return self.update_server.rsyncd_port if self.update_server else None

  def UploadEvent(self, log_name, chunk):
    """Uploads a chunk of events.

    In addition to append events to a single file, we appends event to a
    directory that split on an hourly basis in order to fetch events in a timely
    approach if events_rotate_hourly flag set to True.

    Args:
      log_name: A string of the event log filename. Event logging module creates
          event files with an unique identifier (uuid) as part of the filename.
      chunk: A string containing one or more events. Events are in YAML format
          and separated by a "---" as specified by YAML. A chunk contains one or
          more events with separator.

    Returns:
      True on success.

    Raises:
      IOError if unable to save the chunk of events.
    """
    chunk = self.UnwrapBlob(chunk)

    log_file = os.path.join(self.GetEventsDir(), log_name)
    with open(log_file, 'a') as f:
      f.write(chunk)

    # Wrote events split on an hourly basis
    if self.events_rotate_hourly:
      log_file = os.path.join(self.GetIncrementalEventsDir(), log_name)
      with open(log_file, 'a') as f:
        f.write(chunk)

    return True

  def GetTime(self):
    """Returns the current time in seconds since the epoch."""
    return time.time()

  def UnwrapBlob(self, blob):
    """Unwraps a blob object."""
    return blob.data if isinstance(blob, Binary) else blob


# Alias ShopFloorBase to ShopFloor, so that this module can be run directly.
ShopFloor = ShopFloorBase
