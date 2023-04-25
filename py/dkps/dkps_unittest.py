#!/usr/bin/env python3
# Copyright 2015 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""The DRM Keys Provisioning Server (DKPS) test module."""

import json
import os
import shutil
import subprocess
import tempfile
import unittest

from cros.factory.dkps import dkps
from cros.factory.utils import file_utils
from cros.factory.utils import json_utils
from cros.factory.utils import net_utils
from cros.factory.utils import sync_utils

from cros.factory.external.py_lib import gnupg

SCRIPT_DIR = os.path.dirname(os.path.realpath(__file__))

# Mock key list for testing.
MOCK_KEY_LIST = [
    {'Magic': 'magic001', 'DeviceID': '001', 'Key': 'key001', 'ID': 'id001'},
    {'Magic': 'magic002', 'DeviceID': '002', 'Key': 'key002', 'ID': 'id002'},
    {'Magic': 'magic003', 'DeviceID': '003', 'Key': 'key003', 'ID': 'id003'}]

# Mock encerypted VPD list for testing. This list must contain exactly the same
# number of elements as MOCK_KEY_LIST.
encrypted_vpd_list = [
    '0123456789',
    'qwertyuiop',
    'asdfghjkl;']


# TODO(treapking): Run each test case in a separate function.
class DRMKeysProvisioningServerTest(unittest.TestCase):

  def setUp(self):
    # Create a temp folder for SQLite3 and GnuPG.
    self.temp_dir = tempfile.mkdtemp()
    self.log_file_path = os.path.join(self.temp_dir, 'dkps.log')
    self.database_file_path = os.path.join(self.temp_dir, 'dkps.db')
    self.server_gnupg_homedir = os.path.join(self.temp_dir, 'gnupg', 'server')
    uploader_gnupg_homedir = os.path.join(self.temp_dir, 'gnupg', 'uploader')
    requester_gnupg_homedir = os.path.join(self.temp_dir, 'gnupg', 'requester')
    wrong_user_gnupg_homedir = os.path.join(self.temp_dir, 'gnupg',
                                            'wrong_user')
    os.makedirs(self.server_gnupg_homedir)
    os.makedirs(uploader_gnupg_homedir)
    os.makedirs(requester_gnupg_homedir)
    os.makedirs(wrong_user_gnupg_homedir)

    self.dkps = dkps.DRMKeysProvisioningServer(self.database_file_path,
                                               self.server_gnupg_homedir)
    self.dkps.Initialize(
        server_key_file_path=os.path.join(SCRIPT_DIR, 'testdata', 'server.key'))

    self.db_connection, self.db_cursor = dkps.GetSQLite3Connection(
        self.database_file_path)

    # Retrieve the server key fingerprint.
    self.db_cursor.execute(
        "SELECT * FROM settings WHERE key = 'server_key_fingerprint'")
    self.server_key_fingerprint = self.db_cursor.fetchone()['value']

    # Create server, uploader, requester GPG instances. Export server's public
    # key to uploader and requester.
    self.server_gpg = gnupg.GPG(gnupghome=self.server_gnupg_homedir)
    exported_server_key = self.server_gpg.export_keys(
        self.server_key_fingerprint)
    self.server_key_file_path = os.path.join(self.temp_dir, 'server.pub')
    file_utils.WriteFile(self.server_key_file_path, exported_server_key)

    # TODO(treapking): Extract common procedures into functions or a class.
    self.uploader_gpg = gnupg.GPG(gnupghome=uploader_gnupg_homedir)
    self.uploader_gpg.import_keys(exported_server_key)
    self.requester_gpg = gnupg.GPG(gnupghome=requester_gnupg_homedir)
    self.requester_gpg.import_keys(exported_server_key)
    self.wrong_user_gpg = gnupg.GPG(gnupghome=wrong_user_gnupg_homedir)
    self.wrong_user_gpg.import_keys(exported_server_key)

    # Passphrase for uploader and requester private keys.
    self.passphrase = 'taiswanleba'
    self.passphrase_file_path = os.path.join(self.temp_dir, 'passphrase')
    file_utils.WriteFile(self.passphrase_file_path, self.passphrase)

    self.wrong_passphrase = '_wrong_passphrase_'
    self.wrong_passphrase_file_path = os.path.join(self.temp_dir,
                                                   'wrong_passphrase')
    file_utils.WriteFile(self.wrong_passphrase_file_path, self.wrong_passphrase)

    # Import uploader key.
    self.uploader_key_fingerprint = self.uploader_gpg.import_keys(
        file_utils.ReadFile(
            os.path.join(SCRIPT_DIR, 'testdata',
                         'uploader.key'))).fingerprints[0]
    # Output uploader key to a file for DKPS.AddProject().
    self.uploader_public_key_file_path = os.path.join(self.temp_dir,
                                                      'uploader.pub')
    file_utils.WriteFile(
        self.uploader_public_key_file_path,
        self.uploader_gpg.export_keys(self.uploader_key_fingerprint))
    self.uploader_private_key_file_path = os.path.join(self.temp_dir,
                                                       'uploader')
    file_utils.WriteFile(
        self.uploader_private_key_file_path,
        self.uploader_gpg.export_keys(self.uploader_key_fingerprint, True,
                                      passphrase=self.passphrase))

    # Import requester key.
    self.requester_key_fingerprint = self.requester_gpg.import_keys(
        file_utils.ReadFile(
            os.path.join(SCRIPT_DIR, 'testdata',
                         'requester.key'))).fingerprints[0]
    # Output requester key to a file for DKPS.AddProject().
    self.requester_public_key_file_path = os.path.join(self.temp_dir,
                                                       'requester.pub')
    file_utils.WriteFile(
        self.requester_public_key_file_path,
        self.requester_gpg.export_keys(self.requester_key_fingerprint))
    self.requester_private_key_file_path = os.path.join(self.temp_dir,
                                                        'requester')
    file_utils.WriteFile(
        self.requester_private_key_file_path,
        self.requester_gpg.export_keys(self.requester_key_fingerprint, True,
                                       passphrase=self.passphrase))

    # Import wrong_user key.
    # Note that the passphrase for wrong_user key is "taiswanleba", not
    # "_wrong_passphrase_".
    self.wrong_user_key_fingerprint = self.wrong_user_gpg.import_keys(
        file_utils.ReadFile(
            os.path.join(SCRIPT_DIR, 'testdata',
                         'wrong_user.key'))).fingerprints[0]
    # Output wrong_user key to a file for DKPS.AddProject().
    self.wrong_user_public_key_file_path = os.path.join(self.temp_dir,
                                                        'wrong_user.pub')
    file_utils.WriteFile(
        self.wrong_user_public_key_file_path,
        self.wrong_user_gpg.export_keys(self.wrong_user_key_fingerprint))
    self.wrong_user_private_key_file_path = os.path.join(
        self.temp_dir, 'wrong_user')
    file_utils.WriteFile(
        self.wrong_user_private_key_file_path,
        self.wrong_user_gpg.export_keys(self.wrong_user_key_fingerprint, True,
                                        passphrase=self.passphrase))

    self.server_process = None
    self.port = net_utils.FindUnusedTCPPort()

  def runTest(self):
    self.dkps.AddProject(
        'TestProject', self.uploader_public_key_file_path,
        self.requester_public_key_file_path, 'sample_parser.py',
        'sample_filter.py')

    # Test add duplicate project.
    with self.assertRaisesRegex(ValueError, 'already exists'):
      self.dkps.AddProject(
          'TestProject', self.uploader_public_key_file_path,
          self.requester_public_key_file_path, 'sample_parser.py',
          'sample_filter.py')

    # TODO(littlecvr): Test dkps.UpdateProject().

    # Start the server.
    self.server_process = subprocess.Popen(  # pylint: disable=consider-using-with
        [
            'python3',
            os.path.join(SCRIPT_DIR, 'dkps.py'), '--log_file_path',
            self.log_file_path, '--database_file_path', self.database_file_path,
            '--gnupg_homedir', self.server_gnupg_homedir, 'listen', '--port',
            str(self.port)
        ], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

    sync_utils.WaitFor(lambda: net_utils.ProbeTCPPort(net_utils.LOCALHOST,
                                                      self.port), 2)

    # Upload DRM keys.
    drm_keys_file_path = os.path.join(self.temp_dir, 'mock_drm_keys')
    json_utils.DumpFile(drm_keys_file_path, MOCK_KEY_LIST, pretty=False)
    self._Upload(drm_keys_file_path)

    # Test upload duplicate DRM keys.
    with self.assertRaisesRegex(RuntimeError, 'UNIQUE constraint failed'):
      self._Upload(drm_keys_file_path)

    # Test upload with `--skip_encryption`.
    encrypted_drm_keys_file_path = os.path.join(self.temp_dir,
                                                'encrypted_mock_drm_keys')
    encrypted_mock_drm_keys = self.uploader_gpg.encrypt(
        bytes(json.dumps(MOCK_KEY_LIST), 'utf-8'), self.server_key_fingerprint,
        always_trust=True, sign=self.uploader_key_fingerprint,
        passphrase=self.passphrase, armor=True)
    file_utils.WriteFile(encrypted_drm_keys_file_path,
                         encrypted_mock_drm_keys.data.decode('ascii'))
    with self.assertRaisesRegex(RuntimeError, 'UNIQUE constraint failed'):
      self._Upload(encrypted_drm_keys_file_path, skip_encryption=True)

    # Test upload with wrong encryption key.
    with self.assertRaisesRegex(
        RuntimeError, 'Failed to decrypt the DRM keys: decryption failed'):
      self._Upload(drm_keys_file_path,
                   server_key_file_path=self.wrong_user_public_key_file_path)

    # Test upload with wrong signing key.
    with self.assertRaisesRegex(RuntimeError,
                                'The DRM keys was not signed properly'):
      self._Upload(drm_keys_file_path,
                   client_key_file_path=self.wrong_user_private_key_file_path)

    # Test upload with wrong passphrase.
    with self.assertRaisesRegex(
        RuntimeError,
        'Failed to encrypt and sign the DRM keys: bad passphrase'):
      self._Upload(drm_keys_file_path,
                   passphrase_file_path=self.wrong_passphrase_file_path)

    # Test checking available keys with wrong passphrase.
    with self.assertRaisesRegex(RuntimeError, 'bad passphrase'):
      self._CallHelper(self.requester_private_key_file_path,
                       self.server_key_file_path,
                       self.wrong_passphrase_file_path, 'available')

    # Test checking available keys with wrong signing key.
    with self.assertRaisesRegex(RuntimeError,
                                'Invalid requester, check your signing key'):
      self._CallHelper(self.wrong_user_private_key_file_path,
                       self.server_key_file_path, self.passphrase_file_path,
                       'available')


    # Request and finalize DRM keys.
    for i, mock_key in enumerate(MOCK_KEY_LIST):
      # Check available key count.
      expected_available_key_count = len(MOCK_KEY_LIST) - i
      available_key_count = int(
          self._CallHelper(self.requester_private_key_file_path,
                           self.server_key_file_path, self.passphrase_file_path,
                           'available'))
      self.assertEqual(expected_available_key_count, available_key_count)

      # Request.
      device_serial_number = 'SN%.6d' % i
      serialized_key = self._Request(device_serial_number)
      self.assertEqual(mock_key, json.loads(serialized_key))

    # Test request but insufficient keys left.
    with self.assertRaisesRegex(RuntimeError, 'Insufficient DRM keys'):
      self._Request('INSUFFICIENT_KEY')

    # Test request with wrong encryption key.
    with self.assertRaisesRegex(
        RuntimeError, 'Failed to decrypt the serial number: decryption failed'):
      self._Request('WRONG_SERVER_KEY',
                    server_key_file_path=self.wrong_user_public_key_file_path)

    # Test request with wrong signing key.
    with self.assertRaisesRegex(RuntimeError,
                                'The serial number was not signed properly'):
      self._Request('WRONG_CLIENT_KEY',
                    client_key_file_path=self.wrong_user_private_key_file_path)

    # Test request with wrong passphrase.
    with self.assertRaisesRegex(
        RuntimeError,
        'Failed to encrypt and sign the serial number: bad passphrase'):
      self._Request('WRONG_PASSPHRASE',
                    passphrase_file_path=self.wrong_passphrase_file_path)

    self.dkps.RemoveProject('TestProject')

    # Test remove non-exist project.
    with self.assertRaises(dkps.ProjectNotFoundException):
      self.dkps.RemoveProject('NonExistProject')

    self.dkps.Destroy()

  def tearDown(self):
    if self.server_process:
      self.server_process.terminate()
      self.server_process.wait()

    self.db_connection.close()

    if os.path.exists(self.temp_dir):
      shutil.rmtree(self.temp_dir)

  def _Upload(self, drm_keys_file_path, client_key_file_path=None,
              server_key_file_path=None, passphrase_file_path=None,
              skip_encryption=False):
    if client_key_file_path is None:
      client_key_file_path = self.uploader_private_key_file_path
    if server_key_file_path is None:
      server_key_file_path = self.server_key_file_path
    if passphrase_file_path is None:
      passphrase_file_path = self.passphrase_file_path
    skip_encryption_args = ['--skip_encryption'] if skip_encryption else []

    return self._CallHelper(client_key_file_path, server_key_file_path,
                            passphrase_file_path, 'upload',
                            skip_encryption_args + [drm_keys_file_path])

  def _Request(self, device_serial_number, client_key_file_path=None,
               server_key_file_path=None, passphrase_file_path=None):
    if client_key_file_path is None:
      client_key_file_path = self.requester_private_key_file_path
    if server_key_file_path is None:
      server_key_file_path = self.server_key_file_path
    if passphrase_file_path is None:
      passphrase_file_path = self.passphrase_file_path

    return self._CallHelper(client_key_file_path, server_key_file_path,
                            passphrase_file_path, 'request',
                            [device_serial_number])

  def _CallHelper(self, client_key_file_path, server_key_file_path,
                  passphrase_file_path, command, extra_args=None):
    # TODO(treapking): Load helper module instead so we can have a better error
    # handling.
    extra_args = extra_args if extra_args else []
    try:
      return subprocess.check_output([
          'python3',
          os.path.join(SCRIPT_DIR, 'helpers.py'), '--server_ip', 'localhost',
          '--server_port',
          str(self.port), '--client_key_file_path', client_key_file_path,
          '--server_key_file_path', server_key_file_path,
          '--passphrase_file_path', passphrase_file_path, command, *extra_args
      ], stderr=subprocess.PIPE, encoding='utf-8')
    except subprocess.CalledProcessError as e:
      # Re-raise the error as RuntimeError as CalledProcessError does not
      # include the exception message.
      raise RuntimeError(e.stderr) from None


if __name__ == '__main__':
  unittest.main()
