#!/usr/bin/env python3
# Copyright 2022 The ChromiumOS Authors.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.
"""Unit tests for finalize_bundle."""

import contextlib
import os
import shutil
import tempfile
import unittest
from unittest import mock

from cros.factory.tools import finalize_bundle
from cros.factory.utils import file_utils


class PrepareNetbootTest(unittest.TestCase):
  """Unit tests for preparing netboot."""

  def setUp(self):
    self.temp_dir = tempfile.mkdtemp(prefix='prepare_netboot_unittest_')

  def tearDown(self):
    if os.path.exists(self.temp_dir):
      shutil.rmtree(self.temp_dir)

  def _PrepareDownloadedFiles(self,
                              bundle_builder: finalize_bundle.FinalizeBundle):
    orig_netboot_dir = os.path.join(bundle_builder.bundle_dir, 'factory_shim',
                                    'netboot')
    file_utils.TryMakeDirs(orig_netboot_dir)
    file_utils.TouchFile(
        os.path.join(bundle_builder.bundle_dir, 'factory_shim',
                     'factory_shim.bin'))
    file_utils.TouchFile(os.path.join(orig_netboot_dir, 'vmlinuz'))
    file_utils.TouchFile(os.path.join(orig_netboot_dir, 'image-test.net.bin'))
    bundle_builder.designs = ['test']

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
    self._PrepareDownloadedFiles(bundle_builder)
    bundle_builder.PrepareNetboot()

    self.assertDictEqual(
        file_utils.HashFiles(
            os.path.join(bundle_builder.bundle_dir, 'netboot')), {
                'dnsmasq.conf':
                    '084e4b7f1040bd77555563f49f271213306b8ea5',
                'image-test.net.bin':
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
    self._PrepareDownloadedFiles(bundle_builder)
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


if __name__ == '__main__':
  unittest.main()
