# Copyright 2020 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.
"""Facade for interfacing with various storage mechanisms."""

import abc
import contextlib
import os
import os.path
from typing import Optional, Sequence, Union

from cros.factory.utils import file_utils


class FileSystemAdapterException(Exception):
  """Exceptions of filesystem related operations."""


class NotFoundException(FileSystemAdapterException):
  """Exceptions of file not found while reading/writing/removing files."""


class IFileSystemAdapter(abc.ABC):
  """Abstract class for file access adapters.

  It supports simple, generic operations on files and is meant to provide a
  unified interface to either local or cloud files and provide any necessary
  caching.
  """

  @classmethod
  @abc.abstractmethod
  def GetExceptionMapper(cls):
    """Used to map different type of exceptions in derived classes.

    To provide consistent error handling for derived adapter implementations,
    this method should return an instance of class which implements __enter__
    and __exit__ context methods normalizing various exceptions to
    FileSystemAdapterException.
    """
    raise NotImplementedError('Abstract method not implemented.')

  def ReadFile(self, path: str,
               encoding: Optional[str] = 'utf-8') -> Union[str, bytes]:
    """Read a text file.

    Args:
      path: The path of the file to read.
      encoding: Same param as open(). Set to None for binary mode.

    Returns:
      The string or bytes of the file content.

    Raises:
      FileSystemAdapterException: An error occurred while reading files.
      FileNotFoundException: Raised when the file does not exist.
    """
    with self.GetExceptionMapper():
      return self._ReadFile(path, encoding)

  @abc.abstractmethod
  def _ReadFile(self, path: str,
                encoding: Optional[str] = 'utf-8') -> Union[str, bytes]:
    """The implementation of the read file operation.

    Args: See ReadFile.

    Returns: See ReadFile.

    Raises:
      Exception: Should be converted to FileSystemAdapterException by
        GetExceptionMapper().
    """
    raise NotImplementedError('Abstract method not implemented.')

  def WriteFile(self, path: str, content: Union[str, bytes],
                encoding: Optional[str] = 'utf-8'):
    """Write a text file.

    Args:
      path: The path to write to.
      data: The value to write.  If you need to write bytes, you should set
        encoding to None.
      encoding: Same param as open().  Cannot set to None when content is str.

    Raises:
      FileSystemAdapterException: An error occurred while reading files.
    """
    with self.GetExceptionMapper():
      return self._WriteFile(path, content, encoding)

  @abc.abstractmethod
  def _WriteFile(self, path: str, content: Union[str, bytes],
                 encoding: Optional[str] = 'utf-8'):
    """The implementation of the write file operation.

    Args: See WriteFile.

    Raises:
      Exception: Should be converted to FileSystemAdapterException by
        GetExceptionMapper().
    """
    raise NotImplementedError('Abstract method not implemented.')

  def DeleteFile(self, path: str):
    """Delete a file.

    Args:
      path: The path to delete.

    Raises:
      FileSystemAdapterException: An error occurred while deleting files.
    """
    with self.GetExceptionMapper():
      return self._DeleteFile(path)

  @abc.abstractmethod
  def _DeleteFile(self, path: str):
    """The implementation of the delete file operation.

    Args: See DeleteFile.

    Raises:
      Exception: Should be converted to FileSystemAdapterException by
        GetExceptionMapper().
    """
    raise NotImplementedError('Abstract method not implemented.')

  def ListFiles(self, prefix: Optional[str] = None) -> Sequence[str]:
    """List file under specific prefix/folder.

    Args:
      prefix: The prefix of the file list.

    Returns:
      A list of strings of file paths.

    Raises:
      FileSystemAdapterException: An error occurred while reading files.
    """
    with self.GetExceptionMapper():
      return self._ListFiles(prefix=prefix)

  @abc.abstractmethod
  def _ListFiles(self, prefix: Optional[str] = None) -> Sequence[str]:
    """The implementation of the delete file operation.

    Args: See ListFiles.

    Raises:
      Exception: Should be converted to FileSystemAdapterException by
        GetExceptionMapper().
    """
    raise NotImplementedError('Abstract method not implemented.')


class LocalFileSystemAdapter(IFileSystemAdapter):

  class ExceptionMapper(contextlib.AbstractContextManager):
    def __exit__(self, value_type, value, traceback):
      if isinstance(value, FileNotFoundError):
        raise NotFoundException(str(value)) from value
      if isinstance(value, Exception):
        raise FileSystemAdapterException(str(value)) from value

  EXCEPTION_MAPPER = ExceptionMapper()

  @classmethod
  def GetExceptionMapper(cls):
    """See base class."""
    return cls.EXCEPTION_MAPPER

  def __init__(self, base):
    super().__init__()
    self._base = base

  def _ReadFile(self, path: str,
                encoding: Optional[str] = 'utf-8') -> Union[str, bytes]:
    """See base class."""
    return file_utils.ReadFile(
        os.path.join(self._base, path), encoding=encoding)

  def _WriteFile(self, path: str, content: Union[str, bytes],
                 encoding: Optional[str] = 'utf-8'):
    """See base class."""
    filepath = os.path.join(self._base, path)
    file_utils.TryMakeDirs(os.path.dirname(filepath))
    file_utils.WriteFile(filepath, content, encoding=encoding)

  def _DeleteFile(self, path: str):
    """See base class."""
    filepath = os.path.join(self._base, path)
    file_utils.TryUnlink(filepath)

  def _ListFiles(self, prefix: Optional[str] = None) -> Sequence[str]:
    """Currently _ListFiles implementation only supports directory as prefix."""

    dirpath = self._base
    if prefix:
      dirpath = os.path.join(dirpath, prefix)
    if not os.path.isdir(dirpath):
      raise OSError(f"{dirpath} is not a folder")
    return os.listdir(dirpath)
