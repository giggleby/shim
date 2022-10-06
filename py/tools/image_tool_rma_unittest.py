#!/usr/bin/env python3
#
# Copyright 2018 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

import argparse
import inspect
import os
import shutil
import subprocess
import sys
import tempfile
import threading
import unittest

from cros.factory.tools import image_tool
from cros.factory.unittest_utils import label_utils
from cros.factory.utils import file_utils
from cros.factory.utils import json_utils

DEBUG = False
"""Set DEBUG to True to debug this unit test itself.

The major difference is all output will be preserved in /tmp/t.
"""


class EnvBuilder:
  UPDATER_CONTENT = ('#!/bin/sh\n'
                     'echo \'{"project": {"host": {"versions": '
                     '{"ro": "RO", "rw": "RW"}}}}\'\n')

  PARTITION_COMMANDS = [
      '%(command)s create %(file)s',
      '%(command)s boot -p %(file)s',
      '%(command)s add -i 2 -s 1024 -b 34 -t kernel %(file)s',
      '%(command)s add -i 3 -s 2048 -b 1058 -t rootfs %(file)s',
      '%(command)s add -i 4 -s 1024 -b 3106 -t kernel %(file)s',
      '%(command)s add -i 5 -s 2048 -b 4130 -t rootfs %(file)s',
      '%(command)s add -i 6 -s 1 -b 6178 -t kernel %(file)s',
      '%(command)s add -i 7 -s 1 -b 6179 -t rootfs %(file)s',
      '%(command)s add -i 8 -s 1 -b 6180 -t data %(file)s',
      '%(command)s add -i 9 -s 1 -b 6181 -t reserved %(file)s',
      '%(command)s add -i 10 -s 1 -b 6182 -t reserved %(file)s',
      '%(command)s add -i 11 -s 1 -b 6183 -t firmware %(file)s',
      '%(command)s add -i 12 -s 1 -b 6184 -t efi %(file)s',
      '%(command)s add -i 1 -s 16384 -b 6185 -t data %(file)s',
  ]

  def __init__(self, name, lsb_content):
    self.name = name
    self.temp_dir = None
    self.lsb_content = lsb_content

  def Build(self):
    self.temp_dir = tempfile.mkdtemp()
    self.CreateDiskImage(self.lsb_content)
    self.SetupBundleEnvironment(os.path.join(self.temp_dir, self.name))

  def CreateDiskImage(self, lsb_content):
    cgpt = image_tool.SysUtils.FindCGPT()
    image_path = os.path.join(self.temp_dir, self.name)
    self.CheckCall('truncate -s %s %s' % (16 * 1048576, self.name))

    for command in self.PARTITION_COMMANDS:
      self.CheckCall(command % dict(command=cgpt, file=self.name))
    with image_tool.GPT.Partition.MapAll(image_path) as f:
      self.CheckCall('sudo mkfs -F %sp3' % f)
      self.CheckCall('sudo mkfs -F %sp5' % f)
      self.CheckCall('sudo mkfs -F %sp1 2048' % f)
    with image_tool.Partition(image_path, 3).Mount(rw=True) as d:
      fw_path = os.path.join(d, 'usr', 'sbin', 'chromeos-firmwareupdate')
      self.CheckCall('sudo mkdir -p %s' % os.path.dirname(fw_path))
      tmp_fw_path = os.path.join(self.temp_dir, 'chromeos-firmwareupdate')
      file_utils.WriteFile(tmp_fw_path, self.UPDATER_CONTENT)
      self.CheckCall('sudo mv %s %s' % (tmp_fw_path, fw_path))
      self.CheckCall('sudo chmod a+rx %s' % fw_path)
      common_sh_path = os.path.join(
          d, 'usr', 'share', 'misc', 'chromeos-common.sh')
      self.CheckCall('sudo mkdir -p %s' % os.path.dirname(common_sh_path))
      self.CheckCall('echo "%s" | sudo dd of=%s' %
                     ('#!/bin/sh', common_sh_path))
      lsb_path = os.path.join(d, 'etc', 'lsb-release')
      self.CheckCall('sudo mkdir -p %s' % os.path.dirname(lsb_path))
      self.CheckCall('echo "%s" | sudo dd of=%s' %
                     (lsb_content.strip('\n'), lsb_path))
      write_gpt_path = os.path.join(d, 'usr', 'sbin', 'write_gpt.sh')
      self.CheckCall('sudo mkdir -p %s' % os.path.dirname(write_gpt_path))
      tmp_write_gpt_path = os.path.join(self.temp_dir, 'write_gpt.sh')
      write_command = '\n'.join(
          cmd % dict(command=cgpt, file='$1')
          for cmd in self.PARTITION_COMMANDS)
      file_utils.WriteFile(
          tmp_write_gpt_path,
          '\n'.join([
              '#!/bin/sh',
              'GPT=""',
              'GPT="%s"' % cgpt,  # Override for unit test.
              'write_base_table() {',
              write_command,
              '}',
          ]))
      self.CheckCall('sudo mv %s %s' % (tmp_write_gpt_path, write_gpt_path))

    with image_tool.Partition(image_path, 1).Mount(rw=True) as d:
      lsb_path = os.path.join(d, 'dev_image', 'etc', 'lsb-factory')
      self.CheckCall('sudo mkdir -p %s' % os.path.dirname(lsb_path))
      self.CheckCall('echo "%s" | sudo dd of=%s' %
                     (lsb_content.strip('\n'), lsb_path))
      self.CheckCall('sudo mkdir -p %s' % os.path.join(
          d, 'unencrypted', 'import_extensions'))

  def SetupBundleEnvironment(self, image_path):
    for dir_name in ['factory_shim', 'test_image', 'release_image',
                     'toolkit', 'hwid', 'complete', 'firmware']:
      dir_path = os.path.join(self.temp_dir, dir_name)
      os.makedirs(dir_path)
    for name in ['release_image', 'test_image', 'factory_shim']:
      dest_path = os.path.join(self.temp_dir, name, 'image.bin')
      shutil.copy(image_path, dest_path)
      with image_tool.Partition(dest_path, 3).Mount(rw=True) as d:
        self.CheckCall('echo "%s" | sudo dd of="%s"' %
                       (name, os.path.join(d, 'tag')))
      with image_tool.Partition(dest_path, 1).Mount(rw=True) as d:
        self.CheckCall('echo "%s" | sudo dd of="%s"' %
                       (name, os.path.join(d, 'tag')))
    toolkit_path = os.path.join(self.temp_dir, 'toolkit', 'toolkit.run')
    file_utils.WriteFile(toolkit_path, '#!/bin/sh\necho Toolkit Version 1.0\n')
    os.chmod(toolkit_path, 0o755)

  def Cleanup(self):
    shutil.rmtree(self.temp_dir)

  def CheckCall(self, command):
    return subprocess.check_call(command, shell=True, cwd=self.temp_dir,
                                 stderr=subprocess.DEVNULL)

  def GetToolkitPath(self):
    return os.path.join(self.temp_dir, 'toolkit', 'toolkit.run')

  def GetReleaseImagePath(self):
    return os.path.join(self.temp_dir, 'release_image', 'image.bin')

  def GetTestImagePath(self):
    return os.path.join(self.temp_dir, 'test_image', 'image.bin')

  def GetFactoryShimPath(self):
    return os.path.join(self.temp_dir, 'factory_shim', 'image.bin')


class RMACreateThread(threading.Thread):

  def __init__(self, fn, args):
    super().__init__()
    self.fn = fn
    self.args = args
    self.exception = None

  def run(self):
    try:
      self.fn(*self.args)
    except BaseException as e:
      self.exception = e

  def join(self, timeout=None):
    threading.Thread.join(self)
    if self.exception:
      raise self.exception


# TODO (b/204726360)
@label_utils.Informational
class ImageToolRMATest(unittest.TestCase):
  """Unit tests for image_tool RMA related commands."""

  LSB_CONTENT = 'CHROMEOS_RELEASE_VERSION=1.0\nCHROMEOS_RELEASE_BOARD=%s\n'

  def CheckCall(self, command):
    return subprocess.check_call(command, shell=True, cwd=self.temp_dir)

  def ImageTool(self, *args):
    command = args[0]
    if command == image_tool.CMD_NAMESPACE_RMA:
      command = args[1]
      self.assertIn(command, self.rma_map, 'Unknown command: %s' % command)
      cmd = self.rma_map[command](*self.rma_parsers)
    else:
      self.assertIn(command, self.cmd_map, 'Unknown command: %s' % command)
      cmd = self.cmd_map[command](*self.cmd_parsers)
    cmd.Init()
    cmd_args = self.cmd_parsers[0].parse_args(args)
    cmd_args.verbose = 0
    cmd_args.subcommand.args = cmd_args
    cmd_args.subcommand.Run()

  def setUp(self):
    if DEBUG:
      self.temp_dir = '/tmp/t'
    else:
      self.temp_dir = tempfile.mkdtemp(prefix='image_tool_rma_ut_')
    parser = argparse.ArgumentParser()
    subparser = parser.add_subparsers()
    self.cmd_parsers = (parser, subparser)
    self.cmd_map = dict(
        (v.name, v) for v in image_tool.__dict__.values()
        if inspect.isclass(v) and issubclass(v, image_tool.SubCommand)
        and v.namespace is None)
    rma_parser = subparser.add_parser(image_tool.CMD_NAMESPACE_RMA)
    rma_subparser = rma_parser.add_subparsers()
    self.rma_parsers = (rma_parser, rma_subparser)
    self.rma_map = dict(
        (v.name, v) for v in image_tool.__dict__.values()
        if inspect.isclass(v) and issubclass(v, image_tool.SubCommand)
        and v.namespace == image_tool.CMD_NAMESPACE_RMA)

  def tearDown(self):
    if not DEBUG:
      if os.path.exists(self.temp_dir):
        shutil.rmtree(self.temp_dir)

  def testRMACommands(self):
    """Test RMA related commands.

    To speed up execution time (CreateDiskImage takes ~2s while shutil.copy only
    takes 0.1s) we are testing all commands in one single test case.
    """

    def BuildRMAImage(env_builder, rma_name, active_test_list=None):
      env_builder.Build()
      create_args = [
          'rma',
          'create',
          '--factory_shim',
          env_builder.GetFactoryShimPath(),
          '--test_image',
          env_builder.GetTestImagePath(),
          '--release_image',
          env_builder.GetReleaseImagePath(),
          '--toolkit',
          env_builder.GetToolkitPath(),
          '-o',
          rma_name,
      ]
      if active_test_list:
        create_args += ['--active_test_list', active_test_list]
      self.ImageTool(*create_args)

    os.chdir(self.temp_dir)
    b1 = EnvBuilder('test1.bin', self.LSB_CONTENT % 'test1')
    b2 = EnvBuilder('test2.bin', self.LSB_CONTENT % 'test2')

    t1 = RMACreateThread(BuildRMAImage, (b1, 'rma1.bin'))
    t2 = RMACreateThread(BuildRMAImage, (b2, 'rma2.bin', 'test'))
    t1.start()
    t2.start()
    t1.join()
    t2.join()

    image2_path = os.path.join(b2.temp_dir, b2.name)

    # Verify content of RMA shim.
    DIR_CROS_PAYLOADS = image_tool.CrosPayloadUtils.GetCrosPayloadsDir()
    PATH_CROS_RMA_METADATA = image_tool.CrosPayloadUtils.GetCrosRMAMetadata()
    image_tool.Partition('rma1.bin', 1).CopyFile('tag', 'tag.1')
    image_tool.Partition('rma1.bin', 3).CopyFile('tag', 'tag.3')
    image_tool.Partition('rma1.bin', 1).CopyFile(
        os.path.join(DIR_CROS_PAYLOADS, 'test1.json'), self.temp_dir)
    image_tool.Partition('rma1.bin', 1).CopyFile(
        PATH_CROS_RMA_METADATA, self.temp_dir)
    self.assertEqual(file_utils.ReadFile('tag.1').strip(), 'factory_shim')
    self.assertEqual(file_utils.ReadFile('tag.3').strip(), 'factory_shim')
    data = json_utils.LoadFile('test1.json')
    self.assertEqual(data['toolkit']['version'], u'Toolkit Version 1.0')
    data = json_utils.LoadFile(os.path.basename(PATH_CROS_RMA_METADATA))
    self.assertEqual(data, [{'board': 'test1', 'kernel': 2, 'rootfs': 3}])

    # `rma merge` to merge 2 different shims.
    self.ImageTool(
        'rma', 'merge', '-f', '-o', 'rma12.bin', '-i', 'rma1.bin', 'rma2.bin')
    image_tool.Partition('rma12.bin', 1).CopyFile(
        PATH_CROS_RMA_METADATA, self.temp_dir)
    data = json_utils.LoadFile(os.path.basename(PATH_CROS_RMA_METADATA))
    self.assertEqual(data, [{'board': 'test1', 'kernel': 2, 'rootfs': 3},
                            {'board': 'test2', 'kernel': 4, 'rootfs': 5}])

    # `rma merge` to merge a single-board shim with a universal shim.
    with image_tool.Partition('rma2.bin', 3).Mount(rw=True) as d:
      self.CheckCall('echo "factory_shim_2" | sudo dd of="%s"' %
                     os.path.join(d, 'tag'))
    self.ImageTool(
        'rma', 'merge', '-f', '-o', 'rma12_new.bin',
        '-i', 'rma12.bin', 'rma2.bin', '--auto_select')
    image_tool.Partition('rma12_new.bin', 5).CopyFile('tag', 'tag.5')
    self.assertEqual(file_utils.ReadFile('tag.5').strip(), 'factory_shim_2')

    # `rma extract` to extract a board from a universal shim.
    self.ImageTool('rma', 'extract', '-f', '-o', 'extract.bin',
                   '-i', 'rma12.bin', '-s', '2')
    image_tool.Partition('extract.bin', 1).CopyFile(
        PATH_CROS_RMA_METADATA, self.temp_dir)
    data = json_utils.LoadFile(os.path.basename(PATH_CROS_RMA_METADATA))
    self.assertEqual(data, [{'board': 'test2', 'kernel': 2, 'rootfs': 3}])

    # `rma replace` to replace the factory shim and toolkit.
    factory_shim2_path = os.path.join(self.temp_dir, 'factory_shim2.bin')
    shutil.copy(image2_path, factory_shim2_path)
    with image_tool.Partition(factory_shim2_path, 3).Mount(rw=True) as d:
      self.CheckCall('echo "factory_shim_3" | sudo dd of="%s"' %
                     os.path.join(d, 'tag'))
    toolkit2_path = os.path.join(self.temp_dir, 'toolkit2.run')
    file_utils.WriteFile(toolkit2_path, '#!/bin/sh\necho Toolkit Version 2.0\n')
    os.chmod(toolkit2_path, 0o755)
    self.ImageTool(
        'rma', 'replace', '-i', 'rma12.bin', '--board', 'test2',
        '--factory_shim', factory_shim2_path, '--toolkit', toolkit2_path)
    image_tool.Partition('rma12.bin', 5).CopyFile('tag', 'tag.5')
    self.assertEqual(file_utils.ReadFile('tag.5').strip(), 'factory_shim_3')
    image_tool.Partition('rma12.bin', 1).CopyFile(
        os.path.join(DIR_CROS_PAYLOADS, 'test2.json'), self.temp_dir)
    data = json_utils.LoadFile('test2.json')
    self.assertEqual(data['toolkit']['version'], u'Toolkit Version 2.0')

    b1.Cleanup()
    b2.Cleanup()


if __name__ == '__main__':
  # Support `cros_payload` in bin/ folder.
  new_path = os.path.realpath(os.path.join(
      os.path.dirname(os.path.realpath(__file__)), '..', '..', 'bin'))
  os.putenv('PATH', ':'.join(os.getenv('PATH', '').split(':') + [new_path]))

  sys.path.append(new_path)
  unittest.main()
