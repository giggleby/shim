# Copyright (c) 2013 The Chromium OS Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""VSWR measures the efficiency of the transmission line.

Background:
  SWR (Standing Wave Ratio) is the ratio of the amplitude of a partial
  standing wave at an antinode (maximum) to the amplitude at an adjacent node
  (minimum). SWR is usually defined as a voltage ratio called the VSWR, but
  it is also possible to define the SWR in terms of current, resulting in the
  ISWR, which has the same numerical value. The power standing wave ratio
  (PSWR) is defined as the square of the VSWR.

Why do we need VSWR?
  A problem with transmission lines is that impedance mismatches in the cable
  tend to reflect the radio waves back to the source, preventing the power from
  reaching the destination. SWR measures the relative size of these
  reflections. An ideal transmission line would have an SWR of 1:1, with all
  the power reaching the destination and none of the power reflected back. An
  infinite SWR represents complete reflection, with all the power reflected
  back down the cable.

This test measures VSWR value using an Agilent E5071C Network Analyzer (ENA).
"""


import datetime
import logging
import os
import posixpath
import Queue
import re
import shutil
import StringIO
import time
import unittest
import urllib
import uuid
import xmlrpclib
import yaml

import factory_common  # pylint: disable=W0611

from cros.factory import event_log
from cros.factory.event_log import Log
from cros.factory.goofy.connection_manager import PingHost
from cros.factory.goofy.goofy import CACHES_DIR
from cros.factory.rf.e5071c_scpi import ENASCPI
from cros.factory.rf.utils import CheckPower
from cros.factory.test import factory
from cros.factory.test import shopfloor
from cros.factory.test import test_ui
from cros.factory.test.args import Arg
from cros.factory.test.event import Event
from cros.factory.test.factory import TestState
from cros.factory.test.media_util import MediaMonitor, MountedMedia
from cros.factory.test.utils import TimeString, TryMakeDirs
from cros.factory.utils import file_utils
from cros.factory.utils.net_utils import FindUsableEthDevice
from cros.factory.utils.process_utils import Spawn


class VSWR(unittest.TestCase):
  """A test for antennas using Agilent E5017C Network Analyzer (ENA).

  In general, a pytest runs on a DUT, and runs only once. However, this test
  runs on a host Chromebook that controls the ENA, and runs forever because it
  was designed to test many antennas.

  Ideally, the test won't stop after it has been started. But practically, to
  prevent operators from overusing some accessories. It will stop after reaching
  self._config['test']['max_iterations']. Reminding the operator to change those
  accessories.
  """

  # Items in the final result table.
  _RESULT_IDS = [
      'lte-main', 'lte-aux', 'wifi-main', 'wifi-aux']
  _RESULTS_TO_CHECK = [
      'lte-main', 'lte-aux', 'wifi-main', 'wifi-aux']

  ARGS = [
      Arg('config_path', str, 'Configuration path relative to the root of USB '
          'disk or shopfloor parameters. E.g. path/to/config_file_name.',
          optional=True),
      Arg('timezone', str, 'Timezone of shopfloor.', default='Asia/Taipei'),
      Arg('load_from_shopfloor', bool, 'Whether to load parameters from '
          'shopfloor or not.', default=True),
  ]

  def __init__(self, *args, **kwargs):
    super(VSWR, self).__init__(*args, **kwargs)

    self._config = None
    self._usb_path = None

    self.log = {
        'config': {
            'file_path': None,
            'content': None},
        'dut': {
            'serial_number': None},
        'network_analyzer': {
            'calibration_traces': None,
            'id': None,
            'ip': None},
        'test': {
            'start_time': None,
            'end_time': None,
            'fixture_id': None,
            # TODO(littlecvr): These 2 will always be the same everytime,
            #                  consider removing them?
            'path': os.environ.get('CROS_FACTORY_TEST_PATH'),
            'invocation': os.environ.get('CROS_FACTORY_TEST_INVOCATION'),
            'hash': str(uuid.uuid4()),  # new hash for this iteration
            'traces': {},   # wifi_main, wifi_aux, lte_main, lte_aux
            'results': {},  # wifi_main, wifi_aux, lte_main, lte_aux
            'failures': []}}

  # TODO(littlecvr): Move to the ENA class?
  def _CheckCalibration(self):
    """Checks if the trace are as flat as expected.

    The expected flatness is defined in calibration_check config, which is a
    tuple of:

        ((begin_freqency, end_frequency, sample_points), (min_value, max_value))

    For example:

      ((800*1E6, 6000*1E6, 100), (-0.3, 0.3))

    from 800MHz to 6GHz, sampling 100 points and requires the value to stay
    with in (-0.3, 0.3).
    """
    calibration = self._config['network_analyzer'].get('calibration', None)
    if not calibration:
      raise Exception('No calibration data in config file.')
    logging.info(
        'Checking calibration from %.2f to %.2f with threshold (%f, %f)...',
        calibration['min_frequency'], calibration['max_frequency'],
        calibration['thresholds'][0], calibration['thresholds'][1])
    self._ena.SetSweepSegments([(calibration['min_frequency'],
                                 calibration['max_frequency'],
                                 calibration['sample_points'])])
    TRACES_TO_CHECK = ['S11', 'S22']
    traces = self._ena.GetTraces(TRACES_TO_CHECK)
    calibration_check_passed = True
    for trace_name in TRACES_TO_CHECK:
      trace_data = traces.traces[trace_name]
      for index, freq in enumerate(traces.x_axis):
        check_point = '%s-%15.2f' % (trace_name, freq)
        power_check_passed = CheckPower(
            check_point, trace_data[index], calibration['thresholds'])
        if not power_check_passed:
          # Do not stop, continue to find all failing parts.
          factory.console.info(
              'Calibration check failed at %s', check_point)
          calibration_check_passed = False
    if calibration_check_passed:
      logging.info('Calibration check passed.')
      self.log['network_analyzer']['calibration_traces'] = (
          self._SerializeTraces(traces))
    else:
      raise Exception('Calibration check failed.')

  def _ConnectToENA(self):
    """Connnects to E5071C (ENA) and initializes the SCPI object."""
    # Set up the ENA host.
    logging.info('Connecting to ENA...')
    # TODO(littlecvr): self._FindENA() should be merged into this function so we
    #                  don't have to query its IP from self.log (which is, very
    #                  wierd).
    self._ena = ENASCPI(self.log['network_analyzer']['ip'])
    # Check if this is an expected ENA.
    ena_sn = self._ena.GetSerialNumber()
    logging.info('Connected to ENA %s.', ena_sn)
    # Check if this SN is in the whitelist.
    ena_whitelist = self._config['network_analyzer']['possible_ids']
    if ena_sn not in ena_whitelist:
      self._ena.Close()
      raise ValueError('ENA %s is not in the while list.' % ena_sn)
    self.log['network_analyzer']['id'] = ena_whitelist[ena_sn]
    logging.info('The ENA is now identified as %r.',
                 self.log['network_analyzer']['id'])

  def _DownloadParametersFromShopfloor(self):
    """Downloads parameters from shopfloor."""
    logging.info('Downloading parameters from shopfloor...')
    #caches_dir = os.path.join(CACHES_DIR, 'parameters')

    shopfloor_server = shopfloor.GetShopfloorConnection(retry_interval_secs=3)
    config_content = shopfloor_server.GetParameter(self.args.config_path)

    logging.info('Parameters downloaded.')
    # Parse and load parameters.
    self._LoadConfig(config_content.data)

  def _ResetDataForNextTest(self):
    """Resets internal data for the next testing cycle."""
    logging.info('Reset internal data.')
    self.log['dut']['serial_number'] = None
    self.log['test']['start_time'] = None
    self.log['test']['end_time'] = None
    self.log['test']['hash'] = str(uuid.uuid4())  # new hash for this iteration
    self.log['test']['traces'] = {}  # wifi_main, wifi_aux, lte_main, lte_aux
    self.log['test']['results'] = {}  # wifi_main, wifi_aux, lte_main, lte_aux
    self.log['test']['failures'] = []
    self.log['test']['start_time'] = datetime.datetime.now()

  def _SerializeTraces(self, traces):
    result = {}
    for parameter in traces.parameters:
      response = {}
      for i in range(len(traces.x_axis)):
        response[int(traces.x_axis[i] / 1e6)] = traces.traces[parameter][i]
      result[parameter] = response
    return result

  def _LoadConfig(self, config_content):
    """Reads the configuration from a file."""
    logging.info('Loading config')
    self._config = yaml.load(config_content)

    self.log['config']['file_path'] = self.args.config_path
    self.log['config']['content'] = self._config

  def _SetUSBPath(self, usb_path):
    """Updates the USB device path."""
    self._usb_path = usb_path
    logging.info('Found USB path %s', self._usb_path)

  def _LoadParametersFromUSB(self):
    """Loads parameters from USB."""
    with MountedMedia(self._usb_path, 1) as config_root:
      config_path = os.path.join(config_root, self.args.config_path)
      with open(config_path, 'r') as f:
        self._LoadConfig(f.read())

  def _RaiseUSBRemovalException(self, unused_event):
    """Prevents unexpected USB removal."""
    raise Exception('USB removal is not allowed during test.')

  def _WaitForValidSN(self):
    """Waits for the operator to enter/scan a valid serial number.

    This function essentially does the following things:
      1. Asks the operator to enter/scan a serial number.
      2. Checks if the serial number is valid.
      3. If yes, returns.
      4. If not, shows an error message and goes to step 1.

    After the function's called. self._serial_number would contain the serial
    number entered/scaned by the operator. And self._sn_config would contain
    the config corresponding to that serial number. See description of the
    _GetConfigForSerialNumber() function for more info about 'corresponding
    config.'
    """
    def _GetConfigForSerialNumber(serial_number):
      """Searches the suitable config for this serial number.

      TODO(littlecvr): Move the following description to the module level
                       comment block, where it should state the structure of
                       config file briefly.

      In order to utilize a single VSWR fixture as multiple stations, the
      config file was designed to hold different configs at the same time.
      Thus, this function searches through all the configs and returns the
      first config that matches the serial number, or None if no match.

      For example: the fixture can be configured such that if the serial number
      is between 001 to 100, the threshold is -30 to 0.5; if the serial number
      is between 101 to 200, the threshold is -40 to 0.5; and so forth.

      Returns:
        The first config that matches the serial number, or None if no match.
      """
      for sn_config in self._config['thresholds']:
        if re.search(sn_config['serial_number_regex'], serial_number):
          logging.info('SN matched config %s.', sn_config['name'])
          return sn_config
      return None

    # Reset SN input box and hide error message.
    self._ui.RunJS('$("sn").value = ""')
    self._ui.RunJS('$("sn-format-error").style.display = "none"')
    self._ShowMessageBlock('enter-sn')
    # Loop until the right serial number has been entered.
    while True:
      # Focus and select the text for convenience.
      self._ui.RunJS('$("sn").select()')
      self._WaitForKey(test_ui.ENTER_KEY)
      serial_number = self._GetSN()
      self._sn_config = _GetConfigForSerialNumber(serial_number)
      if self._sn_config:
        self.log['dut']['serial_number'] = serial_number
        return
      else:
        self._ui.RunJS('$("sn-format-error-value").innerHTML = "%s"' %
                       serial_number)
        self._ui.RunJS('$("sn-format-error").style.display = ""')

  # TODO(littlecvr): This function should be moved into the ENA class.
  def _CaptureScreenshot(self, filename_prefix):
    """Captures the screenshot based on the settings.

    Screenshot will be saved in 3 places: ENA, USB disk, and shopfloor (if
    shopfloor is enabled). Timestamp will be automatically added as postfix to
    the output name.

    Args:
      filename_prefix: prefix for the image file name.
    """
    # Save a screenshot copy in ENA.
    filename = '%s[%s]' % (
        filename_prefix, TimeString(time_separator='-', milliseconds=False))
    self._ena.SaveScreen(filename)

    # The SaveScreen above has saved a screenshot inside ENA, but it does not
    # allow reading that file directly (see SCPI protocol for details). To save
    # a copy locally, we need to make another screenshot using ENA's HTTP
    # service (image.asp) which always puts the file publicly available as
    # "disp.png".
    logging.info('Requesting ENA to generate screenshot')
    urllib.urlopen(
        'http://%s/image.asp' % self.log['network_analyzer']['ip']).read()
    png_content = urllib.urlopen(
        'http://%s/disp.png' % self.log['network_analyzer']['ip']).read()
    Log('vswr_screenshot',
        ab_serial_number=self._serial_number,
        path=self._config['event_log_name'],
        filename=filename)

    with file_utils.UnopenedTemporaryFile() as temp_png_path:
      with open(temp_png_path, 'w') as f:
        f.write(png_content)

      # Save screenshot to USB disk.
      formatted_date = time.strftime('%Y%m%d', time.localtime())
      logging.info('Saving screenshot to USB under dates %s', formatted_date)
      with MountedMedia(self._usb_path, 1) as mount_dir:
        target_dir = os.path.join(mount_dir, formatted_date, 'screenshot')
        TryMakeDirs(target_dir)
        filename_in_abspath = os.path.join(target_dir, filename)
        shutil.copyfile(temp_png_path, filename_in_abspath)
        logging.info('Screenshot %s saved in USB.', filename)

      # Save screenshot to shopfloor if needed.
      if self._config['shopfloor_enabled']:
        logging.info('Sending screenshot to shopfloor')
        log_name = os.path.join(self._config['shopfloor_log_dir'],
                                'screenshot', filename)
        self._UploadToShopfloor(
            temp_png_path, log_name,
            ignore_on_fail=self._config['shopfloor_ignore_on_fail'],
            timeout=self._config['shopfloor_timeout'])
        logging.info('Screenshot %s uploaded.', filename)

  def _CheckMeasurement(self, threshold, extracted_value,
                        print_on_failure=False, freq=None, title=None):
    """Checks if the measurement meets the spec.

    Failure details are also recorded in the eventlog. Console display is
    controlled by print_on_failure.

    Args:
      threshold: the pre-defined (min, max) signal strength threshold.
      extracted_value: the value acquired from the trace.
      print_on_failure: If True, outputs failure band in Goofy console.
      freq: frequency to display when print_on_failure is enabled.
      title: title to display for failure message (when print_on_failure is
          True), usually it's one of 'cell_main', 'cell_aux', 'wifi_main',
          'wifi_aux'.
    """
    min_value = threshold[0]
    max_value = threshold[1]
    difference = max(
        (min_value - extracted_value) if min_value else 0,
        (extracted_value - max_value) if max_value else 0)
    check_pass = (difference <= 0)

    if (not check_pass) and print_on_failure:
      # Highlight the failed freqs in console.
      factory.console.info(
          '%10s failed at %.0f MHz[%9.3f dB], %9.3f dB '
          'away from threshold[%s, %s]',
          title, freq / 1000000.0, float(extracted_value),
          float(difference), min_value, max_value)
    # Record the detail for event_log.
    self._vswr_detail_results['%.0fM' % (freq / 1E6)] = {
        'type': title,
        'freq': freq,
        'observed': extracted_value,
        'result': check_pass,
        'threshold': [min_value, max_value],
        'diff': difference}
    return check_pass

  def _CompareTraces(self, traces, lte_or_wifi, main_or_aux, ena_parameter):
    """Returns the traces and spec are aligned or not.

    It calls the check_measurement for each frequency and records
    coressponding result in eventlog and raw logs.

    Usage example:
        self._test_sweep_segment(traces, 'cell', 1, 'cell_main', 'S11')

    Args:
      traces: Trace information from ENA.
      lte_or_wifi: 'cell' or 'wifi' antenna.
      main_or_aux: 'main' or 'aux' antenna.
      ena_parameter: the type of trace to acquire, e.g., 'S11', 'S22', etc.
          Detailed in ena.GetTraces()
    """
    log_title = '%s_%s' % (lte_or_wifi, main_or_aux)
    self._log_to_file.write(
        'Start measurement [%s], with profile[%s,col %s], from ENA-%s\n' %
        (log_title, lte_or_wifi, main_or_aux, ena_parameter))

    # Generate sweep tuples.
    all_passed = True
    results = {}
    for k, v in self._sn_config['%s_%s' % (lte_or_wifi, main_or_aux)].items():
      freq = float(k) * 1e6
      standard = (v[0], v[1])
      response = traces.GetFreqResponse(freq, ena_parameter)
      passed = self._CheckMeasurement(
          standard, response, print_on_failure=True,
          freq=freq, title=log_title)
      results[int(freq / 1e6)] = {
          'value': response,
          'thresholds': standard,
          'passed': passed}
      all_passed = all_passed and passed

      self.log['test']['results'][
          '%s_%s' % (lte_or_wifi, main_or_aux)] = results

    return all_passed

  def _UploadToShopfloor(
      self, file_path, log_name, ignore_on_fail=False, timeout=10):
    """Uploads a file to shopfloor server.

    Args:
      file_path: local file to upload.
      log_name: file_name that will be saved under shopfloor.
      ignore_on_fail: if exception will be raised when upload fails.
      timeout: maximal time allowed for getting shopfloor instance.
    """
    try:
      with open(file_path, 'r') as f:
        chunk = f.read()
      description = 'aux_logs (%s, %d bytes)' % (log_name, len(chunk))
      start_time = time.time()
      shopfloor_client = shopfloor.get_instance(detect=True, timeout=timeout)
      shopfloor_client.SaveAuxLog(log_name, xmlrpclib.Binary(chunk))
      logging.info(
          'Successfully synced %s in %.03f s',
          description, time.time() - start_time)
    except Exception as e:
      if ignore_on_fail:
        factory.console.info(
            'Failed to sync with shopfloor for [%s], ignored', log_name)
        return False
      else:
        raise e
    return True

  def _TestAntennas(self, main_or_aux):
    """Tests either main or aux antenna for both cellular and wifi.

    Args:
      main_or_aux: str, specify which antenna to test, either 'main' or 'aux'.
    """
    # Measure only one big segment.
    self._ena.SetSweepSegments([(
        self._config['network_analyzer']['measure_segment']['min_frequency'],
        self._config['network_analyzer']['measure_segment']['max_frequency'],
        self._config['network_analyzer']['measure_segment']['sample_points'])])
    traces = self._ena.GetTraces(['S11', 'S22'])
    self.log['test']['traces'][main_or_aux] = self._SerializeTraces(traces)

    self._results['lte-%s' % main_or_aux] = (
        TestState.PASSED
        if self._CompareTraces(traces, 'lte', main_or_aux, 'S11') else
        TestState.FAILED)
    self._results['wifi-%s' % main_or_aux] = (
        TestState.PASSED
        if self._CompareTraces(traces, 'wifi', main_or_aux, 'S22') else
        TestState.FAILED)

  def _GenerateFinalResult(self):
    """Generates the final result."""
    self._results['final-result'] = (
        TestState.PASSED
        if all(self._results[f] for f in self._RESULTS_TO_CHECK) else
        TestState.FAILED)
    self.log['test']['end_time'] = datetime.datetime.now()

  def _SaveLog(self):
    """Saves the logs and writes event log."""
    logging.info('Writing log with SN: %s.', self.log['dut']['serial_number'])

    log_file_name = 'log_%s_%s.yaml' % (
        datetime.datetime.now().strftime('%Y%m%d%H%M%S%f')[:-3],  # time
        self.log['dut']['serial_number'])                   # serial number
    log_content = yaml.dump(self.log, default_flow_style=False)

    # Write log file to USB.
    with MountedMedia(self._usb_path, 1) as mount_dir:
      target_dir = os.path.join(
          mount_dir, self._config['test']['shopfloor_log_dir'])
      TryMakeDirs(target_dir)
      full_path = os.path.join(target_dir, log_file_name)
      with open(full_path, 'w') as f:
        f.write(log_content)

    # Feed into event log.
    logging.info('Feeding into event log.')
    event_log_fields = {
        'fixture_id': self.log['test']['fixture_id'],
        'panel_serial': self.log['dut']['serial_number']}
    event_log_fields.update(self.log)
    event_log.Log(self._config['test']['event_log_name'], **event_log_fields)

    logging.info('Uploading aux log onto shopfloor.')
    shopfloor_server = shopfloor.GetShopfloorConnection()
    shopfloor_server.SaveAuxLog(
        posixpath.join(self._config['test']['shopfloor_log_dir'],
                       log_file_name),
        xmlrpclib.Binary(log_content))

  def _SetUpNetwork(self):
    """Sets up the local network.

    The network config should look like the example below:

      network:
        local_ip: !!python/tuple
        - interface:1
        - 192.168.100.20
        - 255.255.255.0
        ena_mapping:
          192.168.100.1:
            MY99999999: Taipei E5071C-mock
          192.168.132.55:
            MY46107723: Line C VSWR 1
            MY46108580: Line C VSWR 2(tds)
            MY46417768: Line A VSWR 3

    About local_ip: use 'eth1' for a specific interface; or 'interface:1' for
    alias, in which 'interface' will be automatically replaced by the default
    interface. And the ':1' part is just a postfix number to distinguish from
    the original interface. You can choose whatever you like. It means the same
    thing as the ifconfig alias. Please refer to ifconfig's manual for more
    detail.
    """
    logging.info('Setting up network...')
    network_config = self._config['dut']['network']

    # Flush route cache just in case.
    Spawn(['ip', 'route', 'flush', 'cache'], check_call=True)
    default_interface = FindUsableEthDevice(raise_exception=True)
    logging.info('Default interface is %s.', default_interface)
    # Use the default interface if local_ip is not given.
    interface = network_config['interface']
    ip = network_config['ip']
    netmask = network_config['netmask']
    self._SetLocalIP(interface, ip, netmask)

  def _SetLocalIP(self, interface, address, netmask):
    """Sets the interface with specific IP address."""
    logging.info(
        'Set interface %s as %s/%s.', interface, address, netmask)
    Spawn(['ifconfig', interface, address, 'netmask', netmask], check_call=True)
    # Make sure the underlying interface is up.
    Spawn(['ifconfig', interface.split(':')[0], 'up'], check_call=True)

  def _FindENA(self):
    """Tries to find the available ENA.

    This function adds the route information for each of the possible ENA in
    the mapping list. In addition, check if there's only one ENA in the visible
    scope.
    """
    interface = self._config['dut']['network']['interface']
    valid_ping_count = 0
    for ena_ip in self._config['network_analyzer']['possible_ips']:
      # Manually add route information for all possible ENAs. Might be
      # duplicated, so ignore the exit code.
      Spawn(['route', 'add', ena_ip, interface], call=True)
      # Flush route cache just in case.
      Spawn(['ip', 'route', 'flush', 'cache'], check_call=True)
      # Ping the host
      logging.info('Searching for ENA at %s...', ena_ip)
      if PingHost(ena_ip, 2) != 0:
        logging.info('Not found at %s.', ena_ip)
      else:
        logging.info('Found ENA at %s.', ena_ip)
        valid_ping_count += 1
        self.log['network_analyzer']['ip'] = ena_ip
    if valid_ping_count != 1:
      raise Exception(
          'Found %d ENAs which should be only 1.' % valid_ping_count)
    logging.info('IP of ENA automatic detected as %s',
                 self.log['network_analyzer']['ip'])

  def _ShowResults(self):
    """Displays the final result."""
    self._ui.SetHTML(self._serial_number, id='result-serial-number')
    for name in self._RESULT_IDS:
      if self._results[name] == TestState.PASSED:
        self._ui.RunJS(
            'document.getElementById("result-%s").style.color = "green"' % name)
      else:
        self._ui.RunJS(
            'document.getElementById("result-%s").style.color = "red"' % name)
      self._ui.SetHTML(self._results[name], id='result-%s' % name)

  def _WaitForEvent(self, subtype):
    """Waits until a specific event subtype has been sent."""
    while True:
      event = self._event_queue.get()
      if hasattr(event, 'subtype') and event.subtype == subtype:
        return event

  def _WaitForKey(self, key):
    """Waits until a specific key has been pressed."""
    # Create a unique event_name for the key and bind it.
    event_name = uuid.uuid4()
    self._ui.BindKey(key, lambda _: self._event_queue.put(
        Event(Event.Type.TEST_UI_EVENT, subtype=event_name)))
    self._WaitForEvent(event_name)
    # Unbind the key and delete the event_name's handler.
    self._ui.UnbindKey(key)

  def _GetSN(self):
    """Gets serial number from HTML input box."""
    self._ui.RunJS('emitSNEnterEvent()')
    event = self._WaitForEvent('snenter')
    return event.data

  def _ShowMessageBlock(self, html_id):
    """Helper function to display HTML message block.

    This function also hides other message blocks as well. Leaving html_id the
    only block to display.
    """
    self._ui.RunJS('showMessageBlock("%s")' % html_id)

  def setUp(self):
    logging.info(
        '(config_path: %s, timezone: %s, load_from_shopfloor: %s)',
        self.args.config_path, self.args.timezone,
        self.args.load_from_shopfloor)

    # Set timezone.
    os.environ['TZ'] = self.args.timezone
    # The following attributes will be overridden when loading config or USB's
    # been inserted.
    self._config = {}
    self._usb_path = ''
    self._serial_number = ''
    self._ena = None
    self._ena_name = None
    # Serial specific config attributes.
    self._sn_config = None
    self._sn_config_name = None
    self._take_screenshot = False
    self._reference_info = False
    self._marker_info = None
    self._sweep_restore = None
    self._vswr_threshold = {}
    # Clear results.
    self._raw_traces = {}
    self._log_to_file = StringIO.StringIO()
    self._vswr_detail_results = {}
    self._iteration_hash = str(uuid.uuid4())
    self._results = {name: TestState.UNTESTED for name in self._RESULT_IDS}
    # Misc.
    self._current_iteration = 0

    # Set up UI.
    self._event_queue = Queue.Queue()
    self._ui = test_ui.UI()
    self._ui.AddEventHandler('keypress', self._event_queue.put)
    self._ui.AddEventHandler('snenter', self._event_queue.put)
    self._ui.AddEventHandler('usbinsert', self._event_queue.put)
    self._ui.AddEventHandler('usbremove', self._event_queue.put)

    # Set up USB monitor.
    self._monitor = MediaMonitor()
    self._monitor.Start(
        on_insert=lambda usb_path: self._ui.PostEvent(Event(
            Event.Type.TEST_UI_EVENT, subtype='usbinsert', usb_path=usb_path)),
        on_remove=lambda usb_path: self._ui.PostEvent(Event(
            Event.Type.TEST_UI_EVENT, subtype='usbremove', usb_path=usb_path)))

  def runTest(self):
    """Runs the test forever or until max_iterations reached.

    At each step, we first call self._ShowMessageBlock(BLOCK_ID) to display the
    message we want. (See the HTML file for all message IDs.) Then we do
    whatever we want at that step, e.g. calling
    self._DownloadParametersFromShopfloor(). Then maybe we wait for some
    specific user's action like pressing the ENTER key to continue, e.g.
    self._WaitForKey(test_ui.ENTER_KEY).
    """
    self._ui.Run(blocking=False)

    # Wait for USB.
    if self.args.load_from_shopfloor:
      self._ShowMessageBlock('wait-for-usb-to-save-log')
    else:
      self._ShowMessageBlock('wait-for-usb-to-load-parameters-and-save-log')
    usb_insert_event = self._WaitForEvent('usbinsert')
    self._SetUSBPath(usb_insert_event.usb_path)
    # Prevent USB from being removed from now on.
    self._ui.AddEventHandler('usbremove', self._RaiseUSBRemovalException)

    # Load config.
    if self.args.load_from_shopfloor:
      self._ShowMessageBlock('download-parameters-from-shopfloor')
      self._DownloadParametersFromShopfloor()
    else:
      self._ShowMessageBlock('load-parameters-from-usb')
      self._LoadParametersFromUSB()

    self._ShowMessageBlock('set-up-network')
    self._SetUpNetwork()

    self._ShowMessageBlock('connect-to-ena')
    self._FindENA()
    self._ConnectToENA()

    self._ShowMessageBlock('check-calibration')
    self._CheckCalibration()

    self._current_iteration = 0
    while True:
      # Force to quit if max iterations reached.
      self._current_iteration += 1
      if (self._config['test']['max_iterations'] and
          self._current_iteration > self._config['test']['max_iterations']):
        factory.console.info('Max iterations reached, please restart.')
        break
      logging.info('Starting iteration %s...', self._current_iteration)

      self._ShowMessageBlock('prepare-panel')
      self._ResetDataForNextTest()
      self._WaitForKey(test_ui.ENTER_KEY)

      self._WaitForValidSN()

      self._ShowMessageBlock('prepare-main-antenna')
      self._WaitForKey('A')

      self._ShowMessageBlock('test-main-antenna')
      self._TestAntennas('main')

      self._ShowMessageBlock('prepare-aux-antenna')
      self._WaitForKey('K')

      self._ShowMessageBlock('test-aux-antenna')
      self._TestAntennas('aux')

      self._GenerateFinalResult()

      self._ShowMessageBlock('save-log')
      self._SaveLog()

      self._ShowResults()
      self._ShowMessageBlock('show-result')
      self._WaitForKey(test_ui.ENTER_KEY)
