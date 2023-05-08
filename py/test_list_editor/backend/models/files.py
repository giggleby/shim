# Copyright 2023 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.
import abc
import os
import threading

from cros.factory.test.env import paths
from cros.factory.test.test_lists import test_list_common


TEST_LIST_CONFIG_DIR = os.path.join(paths.FACTORY_PYTHON_PACKAGE_DIR, 'test',
                                    'test_lists')


class ITestListFile(abc.ABC):
  """Abstract base class for test list files.

  This class defines the interface for saving and loading test list files.
  """

  @abc.abstractmethod
  def Save(self) -> None:
    """Save the test list file."""

  @abc.abstractmethod
  def Load(self) -> None:
    """Load the test list file."""


class TestListFile(ITestListFile):

  def __init__(self, data: dict, filename: str):
    """The container for JSON test list file.

    The `filename` does not need to include ".test_list" or ".json".

    Args:
      data: A dictionary of test items.
      filename: The name of the test list.
    """
    self.data = data
    self.filename = filename

  def Save(self):
    """Saves test list to JSON file.

    Refer to `test_list_common.SaveTestList`.
    """
    test_list_common.SaveTestList(self.data, self.filename)

  def Load(self):
    """Loads test list JSON file to self.data.

    Refer to `test_list_common.LoadTestList`.
    """
    self.data = test_list_common.LoadTestList(self.filename,
                                              TEST_LIST_CONFIG_DIR)


class ITestListFileFactory(abc.ABC):
  """Factory interface of the test list."""

  @abc.abstractmethod
  def Get(self, **kwargs) -> ITestListFile:
    """Abstract method for getting file interface."""


class TestListFileFactory(ITestListFileFactory):
  """Factory interface of the test list."""

  def __init__(self) -> None:
    # TODO: We limit the use case to only consider using JSON file. Revisit this
    # part if we have other use case than JSON.
    self._store = TestListFile

  def Get(self, **kwargs) -> ITestListFile:
    """Return an instance of the test list file.

    Args:
      **kwargs: Additional keyword arguments to pass to the constructor.

    Returns:
      TestListFile: An instance of the test list file.
    """
    return self._store(**kwargs)


_file_factory = None
_file_factory_lock = threading.Lock()


def GetFactoryInstance() -> TestListFileFactory:
  global _file_factory  # pylint: disable=global-statement
  with _file_factory_lock:
    if _file_factory is None:
      _file_factory = TestListFileFactory()
  return _file_factory
