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


class FinalizeBundleTestBase(unittest.TestCase):

  def setUp(self):
    self.temp_dir = tempfile.mkdtemp(prefix=__class__.__name__)

    @contextlib.contextmanager
    def MockTempdir():
      dir_path = os.path.join(self.temp_dir, 'tmp')
      file_utils.TryMakeDirs(dir_path)
      yield dir_path
      shutil.rmtree(dir_path)

    patcher = mock.patch(file_utils.__name__ + '.TempDirectory')
    patcher.start().side_effect = MockTempdir
    self.addCleanup(patcher.stop)

  def tearDown(self):
    if os.path.exists(self.temp_dir):
      shutil.rmtree(self.temp_dir)


class PrepareNetbootTest(FinalizeBundleTestBase):
  """Unit tests for preparing netboot."""

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

    patcher = mock.patch(finalize_bundle.__name__ + '.gsutil.GSUtil.LS')
    patcher.start().side_effect = lambda url: [url]
    self.addCleanup(patcher.stop)

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


class AddFirmwareUpdaterAndImagesTest(FinalizeBundleTestBase):
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

  @classmethod
  def MockMismatchPack(cls, unused_updater_path, dirpath, operation='pack'):
    if operation != 'unpack':
      return
    file_utils.TryMakeDirs(os.path.join(dirpath, 'images'))
    file_utils.WriteFile(
        os.path.join(dirpath, 'manifest.json'), json_utils.DumpStr({}))

  def setUp(self):
    super().setUp()

    @contextlib.contextmanager
    def MockMount(unused_source, unused_index):
      mount_point = os.path.join(self.temp_dir, 'release_mount')
      sbin = os.path.join(mount_point, 'usr/sbin')
      file_utils.TryMakeDirs(sbin)
      file_utils.TouchFile(os.path.join(sbin, 'chromeos-firmwareupdate'))
      yield mount_point
      shutil.rmtree(mount_point)

    patcher = mock.patch(finalize_bundle.__name__ + '.MountPartition')
    patcher.start().side_effect = MockMount
    self.addCleanup(patcher.stop)

    patcher = mock.patch(finalize_bundle.__name__ + '._PackFirmwareUpdater')
    self.pack_mock = patcher.start()
    self.addCleanup(patcher.stop)

    patcher = mock.patch(finalize_bundle.__name__ +
                         '.FinalizeBundle.ExtractFirmwareInfo')
    self.mock_extract_firmware_info = patcher.start()
    self.addCleanup(patcher.stop)


  def _SetupBuilder(self, bundle_builder: finalize_bundle.FinalizeBundle):
    bundle_builder.ProcessManifest()
    bundle_builder.designs = ['test']  # Set by PrepareProjectConfig
    bundle_builder.firmware_image_source = 'mock_fw'  # Set by DownloadResources
    self.mock_extract_firmware_info.return_value = ({}, {
        'randomFWKey': ['test'],
        'randomFWKey1': ['test']
    })

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



class DownloadResourcesTest(FinalizeBundleTestBase):
  """Unit tests of DownloadResources."""

  def setUp(self):
    super().setUp()

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


class CreateFirmwareArchiveFallbackListTest(FinalizeBundleTestBase):

  def testResult(self):
    bundle_builder = finalize_bundle.FinalizeBundle(
        manifest={
            'board': 'brya',
            'project': 'brya',
            'bundle_name': '20210107_evt',
            'toolkit': '15003.0.0',
            'test_image': '14909.124.0',
            'release_image': '15003.0.0',
            'firmware': 'local',
            'netboot_firmware': '12345.67.89',
            'designs': finalize_bundle.BOXSTER_DESIGNS,
        }, work_dir=self.temp_dir)
    bundle_builder.ProcessManifest()
    result = bundle_builder.CreateFirmwareArchiveFallbackList()

    prefix = 'gs://chromeos-releases/dev-channel/brya/'
    self.assertListEqual(result, [
        f'{prefix}12345.67.89/ChromeOS-firmware-*.tar.bz2',
        f'{prefix}12345.67.*/ChromeOS-firmware-*.tar.bz2',
        f'{prefix}12345.*.*/ChromeOS-firmware-*.tar.bz2'
    ])


class ExtractFirmwareInfoTest(FinalizeBundleTestBase):
  """Unit tests of ExtractFirmwareInfo."""

  def setUp(self):
    super().setUp()

    self.config_yaml = None

    @contextlib.contextmanager
    def MockMount(unused_source, unused_index):
      mount_point = os.path.join(self.temp_dir, 'release_mount')
      sbin = os.path.join(mount_point, 'usr/sbin')
      file_utils.TryMakeDirs(sbin)
      file_utils.TouchFile(os.path.join(sbin, 'chromeos-firmwareupdate'))
      config_dir = os.path.join(mount_point, 'usr/share/chromeos-config/yaml')
      file_utils.TryMakeDirs(config_dir)
      file_utils.WriteFile(
          os.path.join(config_dir, 'config.yaml'), self.config_yaml)
      yield mount_point
      shutil.rmtree(mount_point)

    patcher = mock.patch(finalize_bundle.__name__ + '.MountPartition')
    patcher.start().side_effect = MockMount
    self.addCleanup(patcher.stop)

    def MockPack(unused_updater_path, dirpath, operation='pack'):
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
              'randomFWKey_ufs': {
                  'host': {
                      'image': '456'
                  }
              }
          }))
      file_utils.WriteFile(
          os.path.join(dirpath, 'signer_config.csv'),
          'model_name,firmware_image,key_id,ec_image,brand_code\n'
          'randomSignId,image_path,DEFAULT,ec_image_path,ZZCR')

    patcher = mock.patch(finalize_bundle.__name__ + '._PackFirmwareUpdater')
    self.pack_mock = patcher.start()
    self.pack_mock.side_effect = MockPack
    self.addCleanup(patcher.stop)

    patcher = mock.patch('os.path.isfile')
    patcher.start().side_effect = [True, False]
    self.addCleanup(patcher.stop)

    ro_main_firmware = [{
        'hash': 'hash123',
        'version': 'version123'
    }, {
        'hash': 'hash456',
        'version': 'version456'
    }]
    patcher = mock.patch(chromeos_firmware.__name__ +
                         '.CalculateFirmwareHashes')
    self.mock_calculate_fw_hashes = patcher.start()
    self.mock_calculate_fw_hashes.side_effect = ro_main_firmware
    self.addCleanup(patcher.stop)

    fw_keys = {
        'key_recovery': 'hash123',
        'key_root': 'hash456'
    }
    patcher = mock.patch(chromeos_firmware.__name__ + '.GetFirmwareKeys')
    self.mock_get_fw_keys = patcher.start()
    self.mock_get_fw_keys.return_value = fw_keys
    self.addCleanup(patcher.stop)

  def testExtractFirmwareInfo(self):
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

    firmware_record, firmware_manifest_keys = (
        finalize_bundle.FinalizeBundle.ExtractFirmwareInfo('fake_image'))

    self.assertDictEqual(firmware_manifest_keys, {
        'randomFWKey': ['test'],
        'randomFWKey_ufs': ['test']
    })
    self.assertEqual(
        firmware_record, {
            'firmware_records': [{
                'model':
                    'test',
                'firmware_keys': [{
                    'key_id': 'DEFAULT',
                    'key_recovery': 'hash123',
                    'key_root': 'hash456'
                }],
                'ro_main_firmware': [{
                    'hash': 'hash123',
                    'version': 'version123'
                }, {
                    'hash': 'hash456',
                    'version': 'version456'
                }]
            }]
        })

  def testExtractFirmwareInfo_SharedFirmwareKey(self):
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

    firmware_record, firmware_manifest_keys = (
        finalize_bundle.FinalizeBundle.ExtractFirmwareInfo(
            'fake_image', models=['test', 'test15W360']))

    self.assertDictEqual(firmware_manifest_keys,
                         {'randomFWKey': ['test', 'test15W360']})
    self.assertEqual(firmware_record['firmware_records'][0]['firmware_keys'],
                     firmware_record['firmware_records'][1]['firmware_keys'])

  def testExtractFirmwareInfo_Legacy(self):
    self.config_yaml = json_utils.DumpStr({
        'chromeos': {
            'configs': [{
                'name': 'randomFWKey',
                'firmware-signing': {
                    'signature-id': 'randomSignId'
                }
            }]
        }
    })

    firmware_record, firmware_manifest_keys = (
        finalize_bundle.FinalizeBundle.ExtractFirmwareInfo('fake_image'))

    self.assertDictEqual(firmware_manifest_keys,
                         {'randomFWKey': ['randomFWKey']})
    self.assertEqual(
        firmware_record, {
            'firmware_records': [{
                'model':
                    'randomFWKey',
                'firmware_keys': [{
                    'key_id': 'DEFAULT',
                    'key_recovery': 'hash123',
                    'key_root': 'hash456'
                }],
                'ro_main_firmware': [{
                    'hash': 'hash123',
                    'version': 'version123'
                }]
            }]
        })


class CreateRMAShimTest(FinalizeBundleTestBase):
  """Unit tests for CreateRMAShim."""
  default_manifest = {
      'board': 'brya',
      'project': 'brya',
      'bundle_name': '20210107_evt',
      'toolkit': '15003.0.0',
      'test_image': '14909.124.0',
      'release_image': '15003.0.0',
      'firmware': 'release_image/15004.0.0',
      'designs': finalize_bundle.BOXSTER_DESIGNS,
  }

  def _SetupBuilder(self, bundle_builder: finalize_bundle.FinalizeBundle):
    bundle_builder.ProcessManifest()
    bundle_builder.designs = ['test']  # Set by PrepareProjectConfig

  @mock.patch('os.path.getsize', mock.Mock(return_value=1))
  @mock.patch(finalize_bundle.__name__ + '._GetImageTool',
              mock.Mock(return_value=['image_tool']))
  @mock.patch(finalize_bundle.__name__ + '.Spawn')
  def testFlagIsSet_ImageToolIsCalled(self, spawn_mock: mock.Mock):
    bundle_builder = finalize_bundle.FinalizeBundle(
        manifest=self.default_manifest, work_dir=self.temp_dir, rma_shim=True)
    self._SetupBuilder(bundle_builder)

    bundle_builder.CreateRMAShim()

    spawn_mock.assert_called_with([
        'image_tool',
        'rma',
        'create',
        '-f',
        '-o',
        mock.ANY,
        '--board',
        'brya',
        '--project',
        'brya',
        '--designs',
        'test',
    ], log=True, check_call=True, cwd=mock.ANY)

  @mock.patch(finalize_bundle.__name__ + '.Spawn')
  def testFlagIsNotSet_ImageToolIsNotCalled(self, spawn_mock: mock.Mock):
    bundle_builder = finalize_bundle.FinalizeBundle(
        manifest=self.default_manifest, work_dir=self.temp_dir, rma_shim=False)
    self._SetupBuilder(bundle_builder)

    bundle_builder.CreateRMAShim()

    spawn_mock.assert_not_called()


if __name__ == '__main__':
  unittest.main()
