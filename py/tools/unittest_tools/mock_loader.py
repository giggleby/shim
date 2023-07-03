#!/usr/bin/env python3
# Copyright 2021 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

import glob
import os
import shutil
import sys
import tempfile
from typing import List


_PY_PKG_DIR_PATH = os.path.abspath(
    os.path.join(os.path.realpath(__file__), '..', '..', '..', '..', 'py_pkg'))

PY_PKG_PREFIX_PATH = os.path.join('cros', 'factory')


class Loader:

  def __init__(self, exclude_tests: List[str]):
    self._tmp_dir_path = ''
    self._exclude_tests = exclude_tests

  def __enter__(self):
    self._tmp_dir_path = tempfile.mkdtemp()
    fake_path = self._tmp_dir_path
    real_path = os.path.join(self._tmp_dir_path, 'real')

    self._SetupFactoryDir(src_path=_PY_PKG_DIR_PATH, dst_path=fake_path,
                          enable_mocking=True)
    self._SetupFactoryDir(src_path=_PY_PKG_DIR_PATH, dst_path=real_path,
                          enable_mocking=False)

    # Update sys.path by filtering the current factory import path out and
    # insert our fake instead
    sys.path = [p for p in sys.path if 'factory' not in p]
    sys.path.insert(0, self._tmp_dir_path)
    return self

  def __exit__(self, exc_type, exc_value, traceback):
    """Removes the directory created by tempfile.mkdtemp()."""
    shutil.rmtree(self._tmp_dir_path)

  def _SymlinkFile(self, src, dst):
    """Symlinks a file from source to destination."""
    if not os.path.exists(src):
      raise FileNotFoundError(f'{src} not found')
    dir_path = os.path.dirname(dst)
    if not os.path.exists(dir_path):
      os.makedirs(dir_path)
    os.symlink(src, dst)

  def _GenerateExcludeFileList(self):
    exclude_files = set()

    for exclude_path in self._exclude_tests:
      exclude_path = exclude_path.replace('py/', '')
      exclude_file_path = os.path.join(_PY_PKG_DIR_PATH, PY_PKG_PREFIX_PATH,
                                       exclude_path, '**')
      exclude_files |= set(glob.glob(exclude_file_path, recursive=True))

    return exclude_files

  def _SetupFactoryDir(self, src_path, dst_path, enable_mocking):
    """Creates a directory for module importing.

    Args:
    enable_mocking: Determine whether we copy the mocked files
                    instead the real files.
    """
    exclude_files = self._GenerateExcludeFileList()
    files = glob.glob(os.path.join(src_path, '**/*.*'), recursive=True)
    files = [file for file in files if file not in exclude_files]
    file_set = set(files)

    for src_file in files:
      if src_file.endswith('_mocked.py') or os.path.isdir(src_file):
        continue
      dst_file = src_file.replace(src_path, dst_path)
      src_file_name, unused_ext = os.path.splitext(src_file)
      mocked_file = src_file_name + '_mocked.py'
      if enable_mocking and mocked_file in file_set:
        self._SymlinkFile(mocked_file, dst_file)
      else:
        self._SymlinkFile(src_file, dst_file)

  def GetMockedRoot(self):
    """Returns the path of cros package created by this loader."""
    return self._tmp_dir_path
