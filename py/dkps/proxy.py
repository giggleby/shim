# Copyright 2021 The Chromium OS Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.
"""A proxy server for ODM to communicate with DKPS.

This proxy server is implemented for Widevine keybox provisioning on AMD
platform (project spriggins). See go/spriggins-factory-provision for the
detailed design.
"""

import argparse
import hashlib
import json
import logging
import logging.config
import os
import xmlrpc.server

# Use relative import to make this script portable
import helpers


SCRIPT_DIR = os.path.dirname(os.path.realpath(__file__))
DEFAULT_BIND_ADDR = '0.0.0.0'  # all addresses
DEFAULT_BIND_PORT = 5439
DEFAULT_LOG_FILE_NAME = 'dkps_proxy.log'

# Copied from DKPS implementation
DEFAULT_LOGGING_CONFIG = {
    'version': 1,
    'formatters': {
        'default': {
            'format': '%(asctime)s:%(levelname)s:%(funcName)s:'
                      '%(lineno)d:%(message)s'
        }
    },
    'handlers': {
        'file': {
            'class': 'logging.handlers.RotatingFileHandler',
            'formatter': 'default',
            'filename': DEFAULT_LOG_FILE_NAME,
            'maxBytes': 1024 * 1024,  # 1M
            'backupCount': 3
        },
        'console': {
            'class': 'logging.StreamHandler',
            'formatter': 'default',
            'stream': 'ext://sys.stdout'
        }
    },
    'root': {
        'level': 'INFO',
        # only log to file by default, but also log to console if invoked
        # directly from the command line
        'handlers': ['file'] + ['console'] if __name__ == '__main__' else []
    }
}


def _TransportKeyKDF(soc_serial: str, soc_id: int):
  """Generate 128-bit transport key from 32-bit soc_id and 256-bit soc_serial.

  Args:
    soc_serial: SoC serial in hex string format.
    soc_id: SoC model ID.

  Returns:
    The derived transport key in bytes format.
  """

  soc_serial = bytes.fromhex(soc_serial)
  soc_id = soc_id.to_bytes(4, 'little')

  return hashlib.sha256(soc_id + soc_serial).digest()[:16]


def _EncryptWithTransportKey(keybox, transport_key):
  # TODO(treapking): Currently the chroot environment doesn't have pycryptodome
  # installed by default, so we have to import it here to run the unit test in
  # chroot. We should create a docker instance and run factory-server-related
  # unit tests in the future.
  # pylint: disable=import-error
  from Crypto.Cipher import AES

  cipher = AES.new(transport_key, AES.MODE_CBC, b'\0' * 16)
  return cipher.encrypt(bytes.fromhex(keybox)).hex()


class DKPSProxy:

  def __init__(self, helper):
    self.helper = helper

  def Request(self, device_serial_number, soc_serial_number, soc_model_id):
    """Request the DRM key from DKPS and return the keybox re-encrypted with the
    transport key.

    Args:
      device_serial_number: The device serial number assigned by ODM.
      soc_serial_number: The SoC serial number in hex string format.
      soc_model_id: The SoC model ID (integer).

    Returns:
      The encrypted DRM key in hex string format.
    """
    logging.info('Request DRM key from DKPS.')
    keybox = json.loads(self.helper.Request(device_serial_number))

    # Re-encrypt the keybox with the transport key
    logging.info('Re-encrypt DRM key with transport key.')
    transport_key = _TransportKeyKDF(soc_serial_number, soc_model_id)
    keybox = _EncryptWithTransportKey(keybox, transport_key)

    return keybox

  def ListenForever(self, ip, port):
    # Copied from DKPS
    class Server(xmlrpc.server.SimpleXMLRPCServer):

      def _dispatch(self, method, params):
        # Catch exceptions and log them. Without this, SimpleXMLRPCServer simply
        # output the error message to stdout, and we won't be able to see what
        # happened in the log file.
        logging.info('%s called', method)
        try:
          result = xmlrpc.server.SimpleXMLRPCServer._dispatch(
              self, method, params)
          return result
        except BaseException as e:
          logging.exception(e)
          raise

    server = Server((ip, port), allow_none=True)
    server.register_function(self.Request)

    server.serve_forever()


def main():
  parser = argparse.ArgumentParser(description='DKPS proxy server')
  # Arguments for helper.
  parser.add_argument('--server_ip', required=True, help='the key server IP')
  parser.add_argument('--server_port', required=True, type=int,
                      help='the key server port')
  parser.add_argument('--server_key_file_path', required=True,
                      help="path to the server's public key")
  parser.add_argument('--client_key_file_path', required=True,
                      help="path to the client's private key")
  parser.add_argument(
      '--passphrase_file_path', default=None,
      help="path to the passphrase file of the client's "
      'private key')
  # Arguments for proxy server itself.
  parser.add_argument('--ip', default=DEFAULT_BIND_ADDR,
                      help='IP to bind, default to %s' % DEFAULT_BIND_ADDR)
  parser.add_argument('--port', type=int, default=DEFAULT_BIND_PORT,
                      help='port to listen, default to %s' % DEFAULT_BIND_PORT)
  parser.add_argument(
      '-l', '--log_file_path', default=os.path.join(SCRIPT_DIR,
                                                    DEFAULT_LOG_FILE_NAME),
      help='path to the log file, default to "dkps.log" in the same directory '
      'of this script')

  args = parser.parse_args()

  logging_config = DEFAULT_LOGGING_CONFIG
  logging_config['handlers']['file']['filename'] = args.log_file_path
  logging.config.dictConfig(logging_config)

  helper = helpers.RequesterHelper(
      args.server_ip, args.server_port, args.server_key_file_path,
      args.client_key_file_path, args.passphrase_file_path)

  proxy = DKPSProxy(helper)

  proxy.ListenForever(args.ip, args.port)


if __name__ == '__main__':
  main()
