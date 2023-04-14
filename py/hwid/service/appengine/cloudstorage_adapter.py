# Copyright 2018 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.
"""Facade for interfacing with various storage mechanisms."""

import contextlib
import logging
import os.path
from typing import Optional, Sequence, Union

import google.cloud.exceptions
from google.cloud import storage


# isort: split

from cros.factory.hwid.v3 import filesystem_adapter
from cros.factory.utils import type_utils


class CloudStorageAdapter(filesystem_adapter.IFileSystemAdapter):
  """Adapter for Google Cloud Storage."""

  class ExceptionMapper(contextlib.AbstractContextManager):

    def __exit__(self, value_type, value, traceback):
      if isinstance(value, google.cloud.exceptions.NotFound):
        raise filesystem_adapter.NotFoundException(str(value)) from value
      if isinstance(value, Exception):
        raise filesystem_adapter.FileSystemAdapterException(str(value)) from \
            value

  CHUNK_SIZE = 2 ** 20

  EXCEPTION_MAPPER = ExceptionMapper()

  @classmethod
  def GetExceptionMapper(cls):
    """See base class."""
    return cls.EXCEPTION_MAPPER

  def __init__(self, bucket, chunk_size=None):
    self._bucket_name = bucket
    self._chunk_size = chunk_size or self.CHUNK_SIZE

    # Get the dummy project id from env if running on local server, otherwise
    # use the default parameter for staging/prod.
    self._project = os.getenv('CLOUDSDK_CORE_PROJECT')

  @type_utils.LazyProperty
  def _storage_client(self):
    if self._project:
      return storage.Client(project=self._project)
    return storage.Client()

  @type_utils.LazyProperty
  def _storage_bucket(self):
    return self._storage_client.bucket(self._bucket_name)

  def _ReadFile(self, path: str,
                encoding: Optional[str] = 'utf-8') -> Union[str, bytes]:
    """See base class."""
    blob = self._storage_bucket.blob(path)
    return (blob.download_as_text(
        encoding=encoding) if encoding else blob.download_as_bytes())

  def _WriteFile(self, path: str, content: Union[str, bytes],
                 encoding: Optional[str] = 'utf-8'):
    """See base class."""
    blob = self._storage_bucket.blob(path)
    logging.debug('Writing file: %s', blob.path)
    if encoding == 'utf-8' or isinstance(content, bytes):
      blob.upload_from_string(content)
    else:
      blob.upload_from_string(content.encode(encoding))

  def _DeleteFile(self, path: str):
    """See base class."""
    blob = self._storage_bucket.blob(path)
    logging.debug('Deleting file: %s', blob.path)
    blob.delete()

  def _ListFiles(self, prefix: Optional[str] = None) -> Sequence[str]:
    """See base class."""

    if prefix is None:
      prefix = ''

    if prefix and not prefix.endswith('/'):
      prefix += '/'

    ret = []
    for blob in self._storage_client.list_blobs(
        self._bucket_name, prefix=prefix, delimiter='/'):
      ret.append(os.path.relpath(blob.name, prefix))
    return ret
