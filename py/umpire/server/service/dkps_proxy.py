# Copyright 2021 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.
"""A service DKPS proxy server."""

import os

from cros.factory.umpire.server.service import umpire_service
from cros.factory.utils import file_utils
from cros.factory.utils import net_utils

FACTORY_ENV = '/usr/local/factory/bin/factory_env'


def IsDKPSServiceEnabled(umpire_config):
  return ('dkps' in umpire_config['services'] and
          umpire_config['services']['dkps']['active'])


class DKPSProxyService(umpire_service.UmpireService):
  """DKPS proxy service."""

  def CreateProcesses(self, umpire_config, env):
    """Creates list of processes via config.

    Args:
      umpire_config: Umpire config dict.
      env: UmpireEnv object.

    Returns:
      A list of ServiceProcess.
    """
    if IsDKPSServiceEnabled(umpire_config):
      raise RuntimeError(
          'DKPS and its proxy should not run on the same machine.')

    # Workaround for python-gnupg: python-gnupg accesses either
    # os.environ['LOGNAME'] or os.environ['USERNAME'], one of them must exist or
    # python-gnupg will raise a KeyError
    os.environ.setdefault('LOGNAME', 'dkps')

    service_config = umpire_config['services']['dkps_proxy']
    server_ip = service_config.get('server_ip', '')
    server_port = service_config.get('server_port', '')

    if server_ip == '' or server_port == '':
      raise ValueError('service_ip and service_port are required arguments.')

    # Verify the format of server IP.
    net_utils.IP(server_ip)

    # Create folders (recursively) if necessary
    proxy_data_dir = os.path.join(env.umpire_data_dir, 'dkps_proxy')
    file_utils.TryMakeDirs(proxy_data_dir)

    proxy_file_path = os.path.join(env.server_toolkit_dir, 'py', 'dkps',
                                   'proxy.py')

    # TODO(treapking): Add a UI to upload the files in Dome frontend.
    # The keys and the passphrase file should be moved to the hard-coded paths:
    # - Server public key:    {proxy_data_dir}/server.pub
    # - Requeser client key:  {proxy_data_dir}/requester.key
    # - Passphrase file:      {proxy_data_dir}/passphrase
    # If passphrase file does not exist, then we assume that the keys does not
    # have a passphrase.
    cmd = [
        proxy_file_path, '--server_ip', server_ip, '--server_port', server_port,
        '--server_key_file_path', 'server.pub', '--client_key_file_path',
        'requester.key', '--port',
        str(env.umpire_dkps_port), '--log_file_path',
        os.path.join(env.log_dir, 'dkps_proxy.log')
    ]

    if os.path.isfile(os.path.join(proxy_data_dir, 'passphrase')):
      cmd += ['--passphrase', 'passphrase']

    proc_config = {
        'executable': FACTORY_ENV,
        'name': 'dkps_proxy',
        'args': cmd,
        'path': proxy_data_dir
    }
    proc = umpire_service.ServiceProcess(self)
    proc.SetConfig(proc_config)
    return [proc]
