#!/usr/bin/env python3
# Copyright 2022 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.
"""Unit tests for finalize_bundle."""

import contextlib
import os
import shutil
import tempfile
import unittest
from unittest import mock

from cros.factory.probe.functions import chromeos_firmware
from cros.factory.tools import finalize_bundle
from cros.factory.utils import file_utils
from cros.factory.utils import json_utils


class PrepareNetbootTest(unittest.TestCase):
  """Unit tests for preparing netboot."""

  def setUp(self):
    self.temp_dir = tempfile.mkdtemp(prefix='prepare_netboot_unittest_')

  def tearDown(self):
    if os.path.exists(self.temp_dir):
      shutil.rmtree(self.temp_dir)

  def _SetupBuilder(self, bundle_builder: finalize_bundle.FinalizeBundle):
    orig_netboot_dir = os.path.join(bundle_builder.bundle_dir, 'factory_shim',
                                    'netboot')
    file_utils.TryMakeDirs(orig_netboot_dir)
    file_utils.TouchFile(
        os.path.join(bundle_builder.bundle_dir, 'factory_shim',
                     'factory_shim.bin'))
    file_utils.TouchFile(os.path.join(orig_netboot_dir, 'vmlinuz'))
    file_utils.TouchFile(
        os.path.join(orig_netboot_dir, 'image-randomName.net.bin'))
    bundle_builder.designs = ['test']  # Set by PrepareProjectConfig
    # Set by ObtainFirmwareManifestKeys
    bundle_builder.firmware_manifest_keys = {
        'randomFWKey': ['test']
    }
    # Set by AddFirmwareUpdaterAndImages
    bundle_builder.firmware_bios_names = ['randomName']

  @mock.patch(finalize_bundle.__name__ + '.Spawn', mock.Mock())
  def testPrepareNetboot_fromFactoryArchive_verifyFinalLayout(self):
    bundle_builder = finalize_bundle.FinalizeBundle(
        manifest={
            'board': 'brya',
            'project': 'brya',
            'bundle_name': '20210107_pvt',
            'toolkit': '15003.0.0',
            'test_image': '14909.124.0',
            'release_image': '15003.0.0',
            'firmware': 'release_image',
            'designs': finalize_bundle.BOXSTER_DESIGNS,
            'netboot_firmware': '14488.0.0',
        }, work_dir=self.temp_dir)

    bundle_builder.ProcessManifest()
    self._SetupBuilder(bundle_builder)
    bundle_builder.PrepareNetboot()

    self.assertDictEqual(
        file_utils.HashFiles(
            os.path.join(bundle_builder.bundle_dir, 'netboot')), {
                'dnsmasq.conf':
                    '084e4b7f1040bd77555563f49f271213306b8ea5',
                'image-randomName.net.bin':
                    'da39a3ee5e6b4b0d3255bfef95601890afd80709',
                'tftp/chrome-bot/brya/cmdline.sample':
                    'cc137825fb0bf8ed405353b2deffb0c2a4d00b0c',
                'tftp/chrome-bot/brya/vmlinuz':
                    'da39a3ee5e6b4b0d3255bfef95601890afd80709',
            })

  @mock.patch(file_utils.__name__ + '.ExtractFile', mock.Mock())
  @mock.patch(finalize_bundle.__name__ + '.FinalizeBundle._DownloadResource')
  @mock.patch(finalize_bundle.__name__ + '.Spawn', mock.Mock())
  def testPrepareNetboot_fromFirmwareArchive_verifyFinalLayout(
      self, download_mock: mock.MagicMock):

    @contextlib.contextmanager
    def MockDownload(unused_possible_urls, unused_resource_name,
                     unused_version):
      yield (None, None)

    download_mock.side_effect = MockDownload

    bundle_builder = finalize_bundle.FinalizeBundle(
        manifest={
            'board': 'brya',
            'project': 'brya',
            'bundle_name': '20210107_pvt',
            'toolkit': '15003.0.0',
            'test_image': '14909.124.0',
            'release_image': '15003.0.0',
            'firmware': 'release_image',
            'designs': finalize_bundle.BOXSTER_DESIGNS,
            'netboot_firmware': '14489.0.0',
        }, work_dir=self.temp_dir)

    bundle_builder.ProcessManifest()
    self._SetupBuilder(bundle_builder)
    bundle_builder.PrepareNetboot()

    self.assertDictEqual(
        file_utils.HashFiles(
            os.path.join(bundle_builder.bundle_dir, 'netboot')), {
                'dnsmasq.conf':
                    '084e4b7f1040bd77555563f49f271213306b8ea5',
                'tftp/chrome-bot/brya/cmdline.sample':
                    'cc137825fb0bf8ed405353b2deffb0c2a4d00b0c',
                'tftp/chrome-bot/brya/vmlinuz':
                    'da39a3ee5e6b4b0d3255bfef95601890afd80709',
            })


class AddFirmwareUpdaterAndImagesTest(unittest.TestCase):
  """Unit tests for AddFirmwareUpdaterAndImages."""

  @classmethod
  def MockMatchPack(cls, unused_updater_path, dirpath, operation='pack'):
    if operation != 'unpack':
      return
    file_utils.TryMakeDirs(os.path.join(dirpath, 'images'))
    file_utils.WriteFile(
        os.path.join(dirpath, 'manifest.json'),
        json_utils.DumpStr({
            'randomFWKey': {
                'host': {
                    'image': '123'
                }
            },
            'randomFWKey1': {
                'host': {
                    'image': '456'
                }
            }
        }))
    file_utils.WriteFile(
        os.path.join(dirpath, 'signer_config.csv'),
        'model_name,firmware_image,key_id,ec_image,brand_code\n'
        'randomSignId1,image_path,DEFAULT,ec_image_path,ZZCR')

  @classmethod
  def MockMismatchPack(cls, unused_updater_path, dirpath, operation='pack'):
    if operation != 'unpack':
      return
    file_utils.TryMakeDirs(os.path.join(dirpath, 'images'))
    file_utils.WriteFile(
        os.path.join(dirpath, 'manifest.json'), json_utils.DumpStr({}))
    file_utils.WriteFile(os.path.join(dirpath, 'signer_config.csv'), '')

  def setUp(self):
    self.temp_dir = tempfile.mkdtemp(prefix='add_firmware_unittest_')
    self.addCleanup(shutil.rmtree, self.temp_dir)

    @contextlib.contextmanager
    def MockMount(unused_source, unused_index):
      mount_point = os.path.join(self.temp_dir, 'release_mount')
      sbin = os.path.join(mount_point, 'usr/sbin')
      file_utils.TryMakeDirs(sbin)
      file_utils.TouchFile(os.path.join(sbin, 'chromeos-firmwareupdate'))
      config_dir = os.path.join(mount_point, 'usr/share/chromeos-config/yaml')
      file_utils.TryMakeDirs(config_dir)
      file_utils.WriteFile(
          os.path.join(config_dir, 'config.yaml'),
          json_utils.DumpStr({'chromeos': {
              'configs': []
          }}))
      yield mount_point
      shutil.rmtree(mount_point)

    patcher = mock.patch(finalize_bundle.__name__ + '.MountPartition')
    patcher.start().side_effect = MockMount
    self.addCleanup(patcher.stop)

    @contextlib.contextmanager
    def MockTempdir():
      dir_path = os.path.join(self.temp_dir, 'tmp')
      file_utils.TryMakeDirs(dir_path)
      yield dir_path
      shutil.rmtree(dir_path)

    patcher = mock.patch(file_utils.__name__ + '.TempDirectory')
    patcher.start().side_effect = MockTempdir
    self.addCleanup(patcher.stop)

    patcher = mock.patch(finalize_bundle.__name__ + '._PackFirmwareUpdater')
    self.pack_mock = patcher.start()
    self.addCleanup(patcher.stop)

    patcher = mock.patch(chromeos_firmware.__name__ +
                         '.CalculateFirmwareHashes')
    self.mock_calculate_fw_hashes = patcher.start()
    self.addCleanup(patcher.stop)

    patcher = mock.patch(chromeos_firmware.__name__ + '.GetFirmwareKeys')
    self.mock_get_fw_keys = patcher.start()
    self.addCleanup(patcher.stop)

  def _SetupBuilder(self, bundle_builder: finalize_bundle.FinalizeBundle):
    bundle_builder.ProcessManifest()
    bundle_builder.designs = ['test']  # Set by PrepareProjectConfig
    bundle_builder.firmware_image_source = 'mock_fw'  # Set by DownloadResources
    # Set by ObtainFirmwareManifestKeys
    bundle_builder.firmware_manifest_keys = {
        'randomFWKey': ['test'],
        'randomFWKey1': ['test']
    }
    bundle_builder.firmware_sign_ids = {
        'test': {'randomSignId1'}
    }

  def testAddFirmware_protoCrosConfigMismatch_doNotDownloadUpdater(self):
    self.pack_mock.side_effect = self.MockMismatchPack
    bundle_builder = finalize_bundle.FinalizeBundle(
        manifest={
            'board': 'brya',
            'project': 'brya',
            'bundle_name': '20210107_proto',
            'toolkit': '15003.0.0',
            'test_image': '14909.124.0',
            'release_image': '15003.0.0',
            'firmware': 'release_image',
            'designs': finalize_bundle.BOXSTER_DESIGNS,
        }, work_dir=self.temp_dir)

    self._SetupBuilder(bundle_builder)
    bundle_builder.AddFirmwareUpdaterAndImages()

    self.assertDictEqual(
        file_utils.HashFiles(
            os.path.join(bundle_builder.bundle_dir, 'firmware')), {})

  def testAddFirmware_evtCrosConfigMismatch_raiseException(self):
    self.pack_mock.side_effect = self.MockMismatchPack
    bundle_builder = finalize_bundle.FinalizeBundle(
        manifest={
            'board': 'brya',
            'project': 'brya',
            'bundle_name': '20210107_evt',
            'toolkit': '15003.0.0',
            'test_image': '14909.124.0',
            'release_image': '15003.0.0',
            'firmware': 'release_image',
            'designs': finalize_bundle.BOXSTER_DESIGNS,
        }, work_dir=self.temp_dir)

    self._SetupBuilder(bundle_builder)
    self.assertRaisesRegex(KeyError, r'No manifest keys.*',
                           bundle_builder.AddFirmwareUpdaterAndImages)

  def testAddFirmware_evtCrosConfigMatch_downloadUpdater(self):
    self.pack_mock.side_effect = self.MockMatchPack
    bundle_builder = finalize_bundle.FinalizeBundle(
        manifest={
            'board': 'brya',
            'project': 'brya',
            'bundle_name': '20210107_evt',
            'toolkit': '15003.0.0',
            'test_image': '14909.124.0',
            'release_image': '15003.0.0',
            'firmware': 'release_image',
            'designs': finalize_bundle.BOXSTER_DESIGNS,
        }, work_dir=self.temp_dir)

    self._SetupBuilder(bundle_builder)
    bundle_builder.AddFirmwareUpdaterAndImages()

    self.assertDictEqual(
        file_utils.HashFiles(
            os.path.join(bundle_builder.bundle_dir, 'firmware')),
        {'chromeos-firmwareupdate': 'da39a3ee5e6b4b0d3255bfef95601890afd80709'})

  def testAddFirmware_verifyFirmwareRecord(self):
    fw_keys = {
        'key_recovery': 'hash123',
        'key_root': 'hash456'
    }
    ro_main_firmware = [{
        'hash': 'hash123',
        'version': 'version123'
    }, {
        'hash': 'hash456',
        'version': 'version456'
    }]
    self.mock_get_fw_keys.return_value = fw_keys
    self.mock_calculate_fw_hashes.side_effect = ro_main_firmware
    self.pack_mock.side_effect = self.MockMatchPack
    bundle_builder = finalize_bundle.FinalizeBundle(
        manifest={
            'board': 'brya',
            'project': 'brya',
            'bundle_name': '20210107_evt',
            'toolkit': '15003.0.0',
            'test_image': '14909.124.0',
            'release_image': '15003.0.0',
            'firmware': 'release_image',
            'designs': finalize_bundle.BOXSTER_DESIGNS,
        }, work_dir=self.temp_dir)

    self._SetupBuilder(bundle_builder)
    bundle_builder.AddFirmwareUpdaterAndImages()

    self.assertEqual(
        bundle_builder.firmware_record, {
            'firmware_records': [{
                'model': 'test',
                'firmware_keys': [{
                    'key_id': 'DEFAULT',
                    **fw_keys
                }],
                'ro_main_firmware': ro_main_firmware
            }]
        })


class DownloadResourcesTest(unittest.TestCase):
  """Unit tests of DownloadResources."""

  def setUp(self):
    self.temp_dir = tempfile.mkdtemp(prefix='download_resources_unittest_')
    self.addCleanup(shutil.rmtree, self.temp_dir)

    for member in (
        '_CheckGSUtilVersion',
        '_DownloadProjectToolkit',
        '_DownloadFactoryToolkit',
        '_TryDownloadSignedFactoryShim',
    ):
      patcher = mock.patch(finalize_bundle.__name__ +
                           f'.FinalizeBundle.{member}')
      patcher.start()
      self.addCleanup(patcher.stop)

    def MockDownloadTest(requested_version, target_dir):
      target_path = os.path.join(target_dir,
                                 f'mock_test_image_{requested_version}')
      file_utils.TryMakeDirs(target_dir)
      file_utils.TouchFile(target_path)
      return target_path

    patcher = mock.patch(finalize_bundle.__name__ +
                         '.FinalizeBundle._DownloadTestImage')
    patcher.start().side_effect = MockDownloadTest
    self.addCleanup(patcher.stop)

    patcher = mock.patch(finalize_bundle.__name__ +
                         '.FinalizeBundle._DownloadReleaseImage')

    def MockDownloadRelease(requested_version, target_dir):
      target_path = os.path.join(target_dir,
                                 f'mock_release_image_{requested_version}')
      file_utils.TryMakeDirs(target_dir)
      file_utils.TouchFile(target_path)
      return target_path

    patcher.start().side_effect = MockDownloadRelease
    self.addCleanup(patcher.stop)

  def _SetupBuilder(self, bundle_builder: finalize_bundle.FinalizeBundle):
    bundle_builder.ProcessManifest()
    bundle_builder.designs = ['test']  # Set by PrepareProjectConfig

  def testDownloadFirmwareSource_fromReleaseImage(self):
    bundle_builder = finalize_bundle.FinalizeBundle(
        manifest={
            'board': 'brya',
            'project': 'brya',
            'bundle_name': '20210107_evt',
            'toolkit': '15003.0.0',
            'test_image': '14909.124.0',
            'release_image': '15003.0.0',
            'firmware': 'release_image',
            'designs': finalize_bundle.BOXSTER_DESIGNS,
        }, work_dir=self.temp_dir)

    self._SetupBuilder(bundle_builder)
    bundle_builder.DownloadResources()

    self.assertEqual(
        os.path.basename(bundle_builder.firmware_image_source),
        'mock_release_image_15003.0.0')

  def testDownloadFirmwareSource_fromOtherReleaseImage(self):
    bundle_builder = finalize_bundle.FinalizeBundle(
        manifest={
            'board': 'brya',
            'project': 'brya',
            'bundle_name': '20210107_evt',
            'toolkit': '15003.0.0',
            'test_image': '14909.124.0',
            'release_image': '15003.0.0',
            'firmware': 'release_image/15004.0.0',
            'designs': finalize_bundle.BOXSTER_DESIGNS,
        }, work_dir=self.temp_dir)

    self._SetupBuilder(bundle_builder)
    bundle_builder.DownloadResources()

    self.assertEqual(
        os.path.basename(bundle_builder.firmware_image_source),
        'mock_release_image_15004.0.0')

  def testDownloadFirmwareSource_fromLocal(self):
    bundle_builder = finalize_bundle.FinalizeBundle(
        manifest={
            'board': 'brya',
            'project': 'brya',
            'bundle_name': '20210107_evt',
            'toolkit': '15003.0.0',
            'test_image': '14909.124.0',
            'release_image': '15003.0.0',
            'firmware': 'local',
            'designs': finalize_bundle.BOXSTER_DESIGNS,
        }, work_dir=self.temp_dir)

    self._SetupBuilder(bundle_builder)
    bundle_builder.DownloadResources()

    self.assertIsNone(bundle_builder.firmware_image_source)


class ObtainFirmwareManifestKeysTest(unittest.TestCase):
  """Unit tests of ObtainFirmwareManifestKeys."""

  def setUp(self):
    self.temp_dir = tempfile.mkdtemp(prefix='obtain_manifest_keys_unittest_')
    self.addCleanup(shutil.rmtree, self.temp_dir)

    self.config_yaml = None

    @contextlib.contextmanager
    def MockMount(unused_source, unused_index):
      mount_point = os.path.join(self.temp_dir, 'release_mount')
      config_dir = os.path.join(mount_point, 'usr/share/chromeos-config/yaml')
      file_utils.TryMakeDirs(config_dir)
      file_utils.WriteFile(
          os.path.join(config_dir, 'config.yaml'), self.config_yaml)
      yield mount_point
      shutil.rmtree(mount_point)

    patcher = mock.patch(finalize_bundle.__name__ + '.MountPartition')
    patcher.start().side_effect = MockMount
    self.addCleanup(patcher.stop)

  def _CreateBuilder(self):
    bundle_builder = finalize_bundle.FinalizeBundle(
        manifest={
            'board': 'brya',
            'project': 'brya',
            'bundle_name': '20210107_evt',
            'toolkit': '15003.0.0',
            'test_image': '14909.124.0',
            'release_image': '15003.0.0',
            'designs': finalize_bundle.BOXSTER_DESIGNS,
        }, work_dir=self.temp_dir)
    bundle_builder.ProcessManifest()
    bundle_builder.designs = ['test']  # Set by PrepareProjectConfig
    return bundle_builder

  def testObtainFirmwareManifestKeys_MultipleKeys(self):
    self.config_yaml = json_utils.DumpStr({
        'chromeos': {
            'configs': [{
                'name': 'test',
                'firmware': {
                    'image-name': 'randomFWKey'
                },
                'firmware-signing': {
                    'signature-id': 'randomSignId'
                }
            }, {
                'name': 'test',
                'firmware': {
                    'image-name': 'randomFWKey_ufs'
                },
                'firmware-signing': {
                    'signature-id': 'randomSignId'
                }
            }]
        }
    })

    bundle_builder = self._CreateBuilder()
    bundle_builder.ObtainFirmwareManifestKeys()

    self.assertDictEqual(bundle_builder.firmware_manifest_keys, {
        'randomFWKey': ['test'],
        'randomFWKey_ufs': ['test']
    })

  def testObtainFirmwareManifestKeys_SharedFirmwareKey(self):
    self.config_yaml = json_utils.DumpStr({
        'chromeos': {
            'configs': [{
                'name': 'test',
                'firmware': {
                    'image-name': 'randomFWKey'
                },
                'firmware-signing': {
                    'signature-id': 'randomSignId'
                }
            }, {
                'name': 'test15W360',
                'firmware': {
                    'image-name': 'randomFWKey'
                },
                'firmware-signing': {
                    'signature-id': 'randomSignId'
                }
            }]
        }
    })

    bundle_builder = self._CreateBuilder()
    bundle_builder.designs = ['test', 'test15W360']
    bundle_builder.ObtainFirmwareManifestKeys()

    self.assertDictEqual(bundle_builder.firmware_manifest_keys,
                         {'randomFWKey': ['test', 'test15W360']})

  def testObtainFirmwareManifestKeys_Legacy(self):
    self.config_yaml = json_utils.DumpStr({
        'chromeos': {
            'configs': [{
                'name': 'test',
                'firmware-signing': {
                    'signature-id': 'randomSignId'
                }
            }, {
                'name': 'test',
                'firmware-signing': {
                    'signature-id': 'randomSignId'
                }
            }]
        }
    })

    bundle_builder = self._CreateBuilder()
    bundle_builder.ObtainFirmwareManifestKeys()

    self.assertDictEqual(bundle_builder.firmware_manifest_keys,
                         {'test': ['test']})


if __name__ == '__main__':
  unittest.main()
