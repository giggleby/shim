# Copyright 2016 The Chromium OS Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

import logging
import os
import urlparse

import yaml

import factory_common  # pylint: disable=unused-import
from cros.factory.goofy.plugins import plugin
from cros.factory.test.env import paths
from cros.factory.test import shopfloor
from cros.factory.test import testlog_goofy
from cros.factory.utils import process_utils
from cros.factory.utils import sync_utils
from cros.factory.utils import type_utils


_DEV_NULL = open(os.devnull, 'wb')
_DEFAULT_FLUSH_TIMEOUT = 5  # 5sec
_SHOPFLOOR_TIMEOUT = 10  # 10sec
_CLI_HOSTNAME = '0.0.0.0'  # Allows remote connections.
_CLI_PORT = 7000
_TRUNCATE_INTERVAL = 5 * 60  # 5min
_TESTLOG_JSON_MAX_BYTES = 10 * 1024 * 1024  # 10mb


class Instalog(plugin.Plugin):
  """Run Instalog as a Goofy plugin."""

  def __init__(self, goofy, uplink_hostname, uplink_port, uplink_use_shopfloor):
    """Constructor.

    Args:
      goofy: The goofy instance.
      uplink_hostname: Hostname of the target for uploading logs.
      uplink_port: Port of the target for uploading logs.
      uplink_use_shopfloor: Use the configured Shopfloor's IP and port instead.
                            If unable to properly retrieve the IP and port, fall
                            back to uplink_hostname and uplink_port.
    """
    super(Instalog, self).__init__(goofy)
    self._instalog_process = None
    self._config_path = os.path.join(paths.RUNTIME_VARIABLE_DATA_DIR,
                                     'instalog.yaml')

    node_id = testlog_goofy.GetDeviceID()
    data_dir = os.path.join(paths.DATA_LOG_DIR, 'instalog')
    pid_file = os.path.join(paths.RUNTIME_VARIABLE_DATA_DIR, 'instalog.pid')
    log_file = os.path.join(paths.DATA_LOG_DIR, 'instalog.log')
    cli_hostname = _CLI_HOSTNAME
    cli_port = _CLI_PORT
    testlog_json_path = goofy.testlog.primary_json.path
    uplink_enabled = uplink_use_shopfloor or (uplink_hostname and uplink_port)
    if uplink_use_shopfloor:
      url = None
      try:
        url = shopfloor.get_server_url()
      except Exception:
        pass
      if url:
        uplink_hostname = urlparse.urlparse(url).hostname
        uplink_port = urlparse.urlparse(url).port
      elif uplink_hostname and uplink_port:
        logging.error('Instalog: Could not retrieve Shopfloor IP and port; '
                      'falling back to provided uplink "%s:%d"',
                      uplink_hostname, uplink_port)
      else:
        logging.error('Instalog: Could not retrieve Shopfloor IP and port; '
                      'no fallback provided; disabling uplink functionality')
        uplink_enabled = False

    config = {
        'instalog': {
            'node_id': node_id,
            'data_dir': data_dir,
            'pid_file': pid_file,
            'log_file': log_file,
            'cli_hostname': cli_hostname,
            'cli_port': cli_port
        },
        'buffer': {
            'plugin': 'buffer_simple_file',
            'args': {
                'truncate_interval': _TRUNCATE_INTERVAL,
            },
        },
        'input': {
            'testlog_json': {
                'plugin': 'input_testlog_file',
                'targets': 'output_uplink',
                'args': {
                    'path': testlog_json_path,
                    'max_bytes': _TESTLOG_JSON_MAX_BYTES,
                },
            },
        },
        'output': {
            'output_uplink': {
                'plugin': 'output_http',
                'args': {
                    'hostname': uplink_hostname,
                    'port': uplink_port,
                    'url_path': 'instalog'
                },
            }
        },
    }
    if not uplink_enabled:
      del config['output']['output_uplink']

    logging.info('Instalog: Saving config YAML to: %s', self._config_path)
    with open(self._config_path, 'w') as f:
      yaml.dump(config, f, default_flow_style=False)

    # Set reference to the Instalog plugin for testlog
    self.goofy.testlog.SetInstalogPlugin(self)

  def _GetLastSeqProcessed(self):
    """Retrieves the last sequence number processed by Testlog input plugin.

    Returns:
      A tuple of (success, last_seq_processed, result_string).
    """
    p = self._RunCommand(
        ['inspect', 'testlog_json', '.last_event.seq'], read_stdout=True)
    out = p.stdout_data.rstrip()
    if p.returncode == 1:
      return False, None, out
    else:
      try:
        return True, int(out), None
      except Exception:
        return False, None, 'Could not parse output: %s' % out

  def FlushInput(self, last_seq_output, timeout=None):
    """Flushes Instalog's Testlog input plugin.

    Args:
      last_seq_output: The Testlog sequence number up to which flushing should
                       occur.
      timeout: Time to wait before returning with failure.

    Returns:
      A tuple of (success, result_string).
    """
    if timeout is None:
      timeout = _DEFAULT_FLUSH_TIMEOUT
    def CheckLastSeqProcessed():
      success, last_seq_processed, unused_msg = self._GetLastSeqProcessed()
      return success and last_seq_processed >= last_seq_output

    try:
      sync_utils.WaitFor(condition=CheckLastSeqProcessed,
                         timeout_secs=timeout,
                         poll_interval=0.5)
    except type_utils.TimeoutError:
      pass

    success, last_seq_processed, msg = self._GetLastSeqProcessed()
    if not success:
      logging.error('FlushInput: Error encountered: %s', msg)
      return False, msg
    return (last_seq_processed >= last_seq_output,
            'Processed %d / %d events' % (last_seq_processed, last_seq_output))

  def FlushOutput(self, timeout=None):
    """Flushes Instalog's upstream output plugin.

    Args:
      timeout: Time to wait before returning with failure.

    Returns:
      A tuple of (success, result_string).
    """
    if timeout is None:
      timeout = _DEFAULT_FLUSH_TIMEOUT
    p = self._RunCommand(
        ['flush', 'output_uplink', '--timeout', str(timeout)],
        read_stdout=True)
    return p.returncode == 0, p.stdout_data.rstrip()

  def _RunCommand(self, args, verbose=False, **kwargs):
    """Runs an Instalog command using its CLI."""
    cmd_args = ['py/instalog/cli.py', '--config', self._config_path]
    cmd_args.extend(args)
    log_fn = logging.info if verbose else logging.debug
    log_fn('Instalog: Running command: %s', ' '.join(cmd_args))
    return process_utils.Spawn(cmd_args, cwd=paths.FACTORY_DIR, **kwargs)

  @type_utils.Overrides
  def OnStart(self):
    """Called when the plugin starts."""
    self._RunCommand(['start', '--no-daemon'],
                     stdout=_DEV_NULL, stderr=_DEV_NULL)

  @type_utils.Overrides
  def OnStop(self):
    """Called when the plugin stops."""
    self._RunCommand(['stop'], check_output=True, verbose=True)

  @plugin.RPCFunction
  def Archive(self, path, detail):
    state = self._state
    if state == self.STATE.DESTROYED:
      logging.error('Instalog plugin has been destroyed, abort archive')
      return

    try:
      self.Stop()

      def _IsInstalogStopped():
        p = self._RunCommand(['status'], check_output=True)
        return p.stdout_data.strip() == 'DOWN'

      sync_utils.WaitFor(_IsInstalogStopped, timeout_secs=5, poll_interval=1)

      detail = ['-' + 'd' * detail] if detail else []
      self._RunCommand(['archive', '-o', path] + detail, check_call=True)
    finally:
      if state == self.STATE.RUNNING:
        self.Start()
