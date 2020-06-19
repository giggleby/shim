# Copyright 2018 The Chromium OS Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.
"""Facade for interfacing with various storage mechanisms."""

import logging
import os

import cloudstorage  # pylint: disable=import-error

from cros.factory.hwid.v3 import filesystem_adapter


class CloudStorageAdapter(filesystem_adapter.FileSystemAdapter):
  """Adapter for Google Cloud Storage."""

  class ExceptionMapper:

    def __enter__(self):
      pass

    def __exit__(self, value_type, value, traceback):
      if isinstance(value, cloudstorage.errors.NotFoundError):
        raise KeyError(value)
      if isinstance(value, cloudstorage.Error):
        raise filesystem_adapter.FileSystemAdapterException(str(value))

  CHUNK_SIZE = 2 ** 20

  EXCEPTION_MAPPER = ExceptionMapper()

  @classmethod
  def GetExceptionMapper(cls):
    return cls.EXCEPTION_MAPPER

  def __init__(self, bucket, chunk_size=None):
    self._bucket = bucket
    self._chunk_size = chunk_size or self.CHUNK_SIZE

  def _ReadFile(self, path):
    """Read a file from the backing storage system."""
    file_name = self._GsPath(path)

    with cloudstorage.open(file_name) as gcs_file:
      return gcs_file.read()

  def _WriteFile(self, path, content):
    """Create a file in the backing storage system."""
    file_name = self._GsPath(path)

    logging.debug('Writing file: %s', self._GsPath(path))

    with cloudstorage.open(file_name, 'w') as gcs_file:
      gcs_file.write(content)

  def _DeleteFile(self, path):
    """Create a file in the backing storage system."""
    logging.debug('Deleting file: %s', self._GsPath(path))

    cloudstorage.delete(self._GsPath(path))

  def _ListFiles(self, prefix=None):
    """List files in the backing storage system."""

    if prefix is not None and not prefix.endswith('/'):
      prefix += '/'

    files = cloudstorage.listbucket(self._GsPath(), prefix=prefix,
                                    delimiter='/')

    if prefix is None:
      full_prefix = self._GsPath()
    else:
      full_prefix = self._GsPath(prefix)

    return [os.path.relpath(f.filename, full_prefix)
            for f in files if not f.is_dir]

  def _GsPath(self, *pieces):
    return os.path.normpath('/'.join(['', self._bucket] + list(pieces)))