# Copyright 2016 The Chromium OS Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Tests RF chip's transmitting and receiving capabilities using Graphyte.

Usage example::

  FactoryTest(
      id='RFConductive',
      label=_('RF Conductive'),
      pytest_name='rf_graphyte',
      dargs={
          'graphyte_config_file': 'conductive_config.json',
          'verbose': True,
          'enable_shopfloor': True,
          'shopfoor_parameter_dir': 'rf_conductive',
          'shopfloor_log_dir': 'rf_conductive'})
"""

import csv
import json
import logging
import os
import subprocess
import time
import unittest

import factory_common  # pylint: disable=unused-import
from cros.factory.device import device_utils
from cros.factory.test.env import paths
from cros.factory.test import factory
from cros.factory.test.i18n import test_ui as i18n_test_ui
from cros.factory.test import shopfloor
from cros.factory.test import state
from cros.factory.test import test_ui
from cros.factory.test import ui_templates
from cros.factory.testlog import testlog
from cros.factory.utils.arg_utils import Arg


# The Graphyte config files (pathloss, test plan, port config) should be placed
# in the rf_graphyte folder.
LOCAL_CONFIG_DIR = os.path.dirname(os.path.abspath(__file__))
# The log files are in the default log folder.
RESULT_FILENAME = 'graphyte_result.csv'
LOG_FILENAME = 'graphyte.log'

_ID_MSG_DIV = '_msg'
_ID_DEBUG_DIV = '_debug'

_CSS = """
  #%s {
    font-size: 2em;
    color: blue;
  }
  #%s {
    text-align: left;
    height: 70%%;
    overflow: auto;
  }
""" % (_ID_MSG_DIV, _ID_DEBUG_DIV)

_STATE_HTML = """
  <div id='%s'></div>
  <div id='%s'></div>
""" % (_ID_MSG_DIV, _ID_DEBUG_DIV)

_MSG_FETCH_CONFIG = i18n_test_ui.MakeI18nLabelWithClass(
    'Fetching config files from shopfloor', 'message')
_MSG_EXECUTE_GRAPHYTE = i18n_test_ui.MakeI18nLabelWithClass(
    'Executing Graphyte', 'message')
_MSG_UPLOAD_RESULT = i18n_test_ui.MakeI18nLabelWithClass(
    'Uploading result files to shopfloor', 'message')

class RFGraphyteTest(unittest.TestCase):

  ARGS = [
      Arg('graphyte_config_file', str,
          'Path to Graphyte config file. This is interpreted as the path '
          'relative to `test/pytests/rf_graphyte` folder.',
          optional=False),
      Arg('patch_dhcp_ssh_dut_ip', bool,
          'Set to True if Goofy uses SSH link with DHCP enabled to connect to '
          "DUT. This will patch the IP from Goofy's link into Graphyte's "
          'target DUT IP configuration.',
          default=False, optional=True),
      Arg('verbose', bool, 'Enable Graphyte debug logging',
          default=True, optional=True),
      Arg('enable_shopfloor', bool,
          'Whether or not to use shopfloor. If True, the test will try to '
          'update config files from shopfloor, and upload the log and result '
          'file to shopfloor server. If False, the test will load config file '
          'from local disk and does not upload log.',
          default=True, optional=False),
      Arg('shopfloor_parameter_dir', str,
          'Directory in which to place the updated config files. All the files '
          'in this folder will be downloaded to `test/pytests/rf_graphyte` '
          'folder. Only takes effect if "enable_shopfloor" is set to True.',
          default='rf_graphyte', optional=True),
      Arg('shopfloor_log_dir', str, 'Directory in which to save logs on '
          'shopfloor.  For example: "wifi_radiated".  Only takes effect if '
          '"enable_shopfloor" is set to True.',
          default='rf_graphyte', optional=True),
      ]

  def setUp(self):
    self._ui = test_ui.UI()
    self._ui.AppendCSS(_CSS)
    self._template = ui_templates.OneSection(self._ui)
    self._template.SetState(_STATE_HTML)
    self._dut = device_utils.CreateDUTInterface()
    self.process = None
    if self.args.enable_shopfloor:
      self._shopfloor_proxy = shopfloor.GetShopfloorConnection()

    timestamp = time.strftime('%H%M%S')
    self.config_file_path = os.path.join(
        LOCAL_CONFIG_DIR, self.args.graphyte_config_file)
    self.result_file_path = self.GetLogPath(timestamp, RESULT_FILENAME)
    self.log_file_path = self.GetLogPath(timestamp, LOG_FILENAME)

  def tearDown(self):
    if self.process:
      logging.info('Graphyte process still exists, kill the process (pid: %s).',
                   self.process.pid)
      self.process.kill()

  def runTest(self):
    self._ui.RunInBackground(self._runTest)
    self._ui.Run()

  def _runTest(self):
    # Update the config file from shopfloor.
    self.FetchConfigFromShopfloor()

    # Check the config file exists.
    if not os.path.exists(self.config_file_path):
      self.fail('Graphyte config file %s does not exist.' %
                self.config_file_path)

    # Patch the DUT config with DHCP IP.
    if self.args.patch_dhcp_ssh_dut_ip:
      self.PatchSSHLinkConfig()

    testlog.AttachFile(
        path=self.config_file_path,
        mime_type='application/json',
        name='graphyte_config.json',
        description=os.path.basename(self.config_file_path),
        delete=False)

    # Execute Graphyte.
    self._ui.SetHTML(_MSG_EXECUTE_GRAPHYTE, id=_ID_MSG_DIV)
    cmd = ['python', '-m', 'graphyte.main',
           '--config-file', self.config_file_path,
           '--result-file', self.result_file_path,
           '--log-file', self.log_file_path]
    if self.args.verbose:
      cmd.append('-v')
    factory.console.info('Call the Graphyte command: %s', ' '.join(cmd))
    self.process = subprocess.Popen(cmd, stdout=subprocess.PIPE)

    # Output to UI
    debug_str = ''
    while True:
      line = self.process.stdout.readline()
      if not line:
        break
      # Keep 8Kb data.
      debug_str = (test_ui.Escape(line) + debug_str)[:8 * 1024]
      self._ui.SetHTML(debug_str, id=_ID_DEBUG_DIV)
    self.process = None

    # Save the log file.
    if os.path.exists(self.log_file_path):
      testlog.AttachFile(
          path=self.log_file_path,
          mime_type='text/plain',
          name='graphyte.log',
          description=os.path.basename(self.log_file_path),
          delete=False)

    # Save the result file.
    if os.path.exists(self.result_file_path):
      testlog.AttachFile(
          path=self.result_file_path,
          mime_type='text/csv',
          name='graphyte_result.csv',
          description=os.path.basename(self.result_file_path),
          delete=False)

    # Parse result file.
    if not os.path.exists(self.result_file_path):
      self.fail('Result file is not found.')
    with open(self.result_file_path) as result_file:
      result_data = result_file.read()
      logging.debug('Graphyte result: %s', result_data)
      factory.console.info('Graphyte result:\n%s', result_data)
      failed_results = [result for result in result_data.splitlines()
                        if 'FAIL' in result]
      if failed_results:
        factory.console.error('Failed result:\n%s', '\n'.join(failed_results))

    # Upload the log to shopfloor and testlog.
    try:
      self.UploadResultToShopfloor()
    except Exception as e:
      logging.exception(e)
      logging.error('Error uploading logs to shopfloor: %s: %s',
                    e.__class__.__name__, e)
    try:
      self.SaveParamsToTestlog()
    except Exception as e:
      logging.exception(e)
      logging.error('Error saving params to testlog: %s: %s',
                    e.__class__.__name__, e)

    # Total test result is at the last column of the last row.
    result_lines = result_data.splitlines()
    try:
      final_result = result_lines[-1].split(',')[-1]
    except Exception as e:
      logging.exception(e)
      self.fail('Corrupt or incomplete result file %s: %s: %s'
                % (self.result_file_path, e.__class__.__name__, e))

    # Pass or fail the pytest.
    self.assertEquals(final_result, 'PASS')

  def GetLogPath(self, timestamp, suffix):
    """Get the file path of Graphyte output files.

    To keep the output file for every DUT, we add serial number and timestamp to
    make the file name unique.
    """
    # Workaround: Get the serial number without InfoProperty.
    # https://bugs.chromium.org/p/chromium/issues/detail?id=707200
    # Revert it after the issue is resolved.
    mlb_serial_number = state.GetSerialNumber(state.KEY_MLB_SERIAL_NUMBER)
    file_name = '%s_%s_%s' % (
        mlb_serial_number, timestamp, suffix)
    # save the log under /var/factory/tests/<TestID>-<UUID>/
    current_test_dir = os.path.join(paths.DATA_TESTS_DIR,
                                    factory.get_current_test_path())
    return os.path.join(current_test_dir, file_name)

  def PatchSSHLinkConfig(self):
    """Patch the DHCP IP in the DUT config.

    The DUT config might be in three places: device default config, overridden
    config file, overridden config in the global config file. Since the last one
    will override the previous config, we directly patch the DHCP IP in the
    global config file. Please refer "Graphyte Use Manual" for detail.
    """
    with open(self.config_file_path, 'r') as f:
      global_config = json.load(f)

    # Override DUT link IP in the global config file.
    global_config.setdefault('dut_config', {})
    global_config['dut_config'].setdefault('link_options', {})
    global_config['dut_config']['link_options']['host'] = self._dut.link.host

    # Write the patched config into new config file.
    self.config_file_path += '.patched'
    with open(self.config_file_path, 'w') as f:
      json.dump(global_config, f)

  def FetchConfigFromShopfloor(self):
    """Fetch all config files from shopfloor.

    The Graphyte config file lists other needed files, such as port config, test
    plan, and DUT/instrument config file. Since we don't only need one config
    file, we fetch all config files at the shopfloor to local side.
    """
    if not self.args.enable_shopfloor:
      return

    self._ui.SetHTML(_MSG_FETCH_CONFIG, id=_ID_MSG_DIV)
    config_file_paths = self._shopfloor_proxy.ListParameters(
        os.path.join(self.args.shopfloor_parameter_dir, '*'))
    for file_path in config_file_paths:
      factory.console.info('Fetch config file from shopfloor: %s', file_path)
      content = self._shopfloor_proxy.GetParameter(file_path).data
      file_name = os.path.basename(file_path)
      with open(os.path.join(LOCAL_CONFIG_DIR, file_name), 'w') as f:
        f.write(content)

  def UploadResultToShopfloor(self):
    """Upload Graphyte log and result to shopfloor."""
    if not self.args.enable_shopfloor:
      return

    self._ui.SetHTML(_MSG_UPLOAD_RESULT, id=_ID_MSG_DIV)
    output_files = [self.result_file_path, self.log_file_path]
    factory.console.info('Upload the result to shopfloor: %s', output_files)
    for output_file in output_files:
      try:
        shopfloor.UploadAuxLogs([output_file], True,
                                dir_name=self.args.shopfloor_log_dir)
      except Exception as e:
        logging.exception(e)
        logging.error('Could not upload %s: %s: %s',
                      output_file, e.__class__.__name__, e)

  def SaveParamsToTestlog(self):
    def _ConvertToNumber(value):
      """Convert the string to a number or None."""
      try:
        return float(value)
      except ValueError:
        return None

    with open(self.result_file_path, 'r') as f:
      for data in csv.DictReader(f):
        if data['test_item'] == 'TOTAL RESULT':
          continue

        parameters = ParseGraphyteTestName(data['test_item'])
        parameters['result_name'] = data['result_name']
        parameters['power_level'] = _ConvertToNumber(data['power_level'])
        test_name = json.dumps(parameters)
        result_value = _ConvertToNumber(data['result'])
        if result_value is None:
          code = 'GraphyteResultMissing'
          details = '%s result is missing.' % test_name
          testlog.AddFailure(code=code, details=details)
        else:
          try:
            testlog.CheckParam(name=test_name,
                               value=result_value,
                               min=_ConvertToNumber(data['lower_bound']),
                               max=_ConvertToNumber(data['upper_bound']))
          except Exception as e:
            logging.exception(e)
            logging.error('Could not run CheckParam for data=%r: %s: %s',
                          data, e.__class__.__name__, e)


def ParseGraphyteTestName(test_name):
  """Parse the test arguments from the test name."""
  def _ConvertDataType(value_str):
    if value_str in ['', 'None', 'none']:
      return None
    try:
      return int(value_str)
    except ValueError:
      pass
    try:
      return float(value_str)
    except ValueError:
      pass
    return value_str

  items = map(_ConvertDataType, test_name.split(' '))
  if items[0] == 'WLAN':
    fields = ['rf_type', 'component_name', 'test_type', 'center_freq',
              'standard', 'data_rate', 'bandwidth', 'chain_mask']
  elif items[0] == 'BLUETOOTH':
    fields = ['rf_type', 'component_name', 'test_type', 'center_freq',
              'packet_type']
  elif items[0] == '802_15_4':
    fields = ['rf_type', 'component_name', 'test_type', 'center_freq']
  else:
    logging.error('Should not be here. items: %s', items)
  assert len(items) == len(fields), 'items %s, fields %s' % (items, fields)
  return dict(zip(fields, items))
