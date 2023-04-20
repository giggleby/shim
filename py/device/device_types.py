# Copyright 2017 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Interfaces, classes and types for Device API."""

import abc
from typing import IO, Any, Optional, Sequence, Union, overload

from cros.factory.utils import sys_interface
from cros.factory.utils import type_utils


# Default component property - using lazy loaded property implementation.
DeviceProperty = type_utils.LazyProperty

# Use sys_interface.CalledProcessError for invocation exceptions.
CalledProcessError = sys_interface.CalledProcessError

CommandsToShell = sys_interface.CommandsToShell


class DeviceException(Exception):
  """Common exception for all components."""


class DeviceLink(abc.ABC):
  """An abstract class for connection to remote or local device."""

  @abc.abstractmethod
  def Push(self, local: str, remote: str) -> None:
    """Uploads a local file to target device.

    Args:
      local: A string for local file path.
      remote: A string for remote file path on device.
    """
    raise NotImplementedError

  @abc.abstractmethod
  def PushDirectory(self, local: str, remote: str) -> None:
    """Copies a local file to target device.

    `local` should be a local directory, and `remote` should be a non-existing
    file path on device.

    Example::

     PushDirectory('/path/to/local/dir', '/remote/path/to/some_dir')

    Will create directory `some_dir` under `/remote/path/to` and copy
    files and directories under `/path/to/local/dir/` to `some_dir`.

    Args:
      local: A string for directory path in local.
      remote: A string for directory path on remote device.
    """
    raise NotImplementedError

  @abc.abstractmethod
  @overload
  def Pull(self, remote: str, local: None = None) -> Union[str, bytes]:
    ...

  @abc.abstractmethod
  @overload
  def Pull(self, remote: str, local: str) -> None:
    ...

  @abc.abstractmethod
  def Pull(self, remote: str, local: Optional[str] = None):
    """Downloads a file from target device to local.

    Args:
      remote: A string for file path on remote device.
      local: A string for local file path to receive downloaded content, or
             None to return the contents directly.

    Returns:
      If local is None, return bytes or a string as contents in remote file.
      Otherwise, do not return anything.
    """
    raise NotImplementedError

  @abc.abstractmethod
  def PullDirectory(self, remote: str, local: str) -> None:
    """Downloads a directory from target device to local."""
    raise NotImplementedError

  @abc.abstractmethod
  def Shell(self, command: Union[str, Sequence[str]],
            stdin: Union[None, int,
                         IO[Any]] = None, stdout: Union[None, int,
                                                        IO[Any]] = None,
            stderr: Union[None, int, IO[Any]] = None, cwd: Optional[str] = None,
            encoding: Optional[str] = 'utf-8') -> Any:
    """Executes a command on device.

    The calling convention is similar to subprocess.Popen, but only a subset of
    parameters are supported due to platform limitation.

    Args:
      command: A string or a list of strings for command to execute.
      stdin: A file object to override standard input.
      stdout: A file object to override standard output.
      stderr: A file object to override standard error.
      cwd: The working directory for the command.
      encoding: Same as subprocess.Popen, we will use `utf-8` as default to make
          it output str type.

    Returns:
      An object representing the process, similar to subprocess.Popen.
    """
    raise NotImplementedError

  @abc.abstractmethod
  def IsReady(self) -> bool:
    """Checks if device is ready for connection.

    Returns:
      A boolean indicating if target device is ready.
    """
    raise NotImplementedError

  @abc.abstractmethod
  def IsLocal(self) -> bool:
    """Checks if the target device exactly the local machine.

    This is helpful for tests to decide if they can use Python native modules or
    need to invoke system commands.

    Returns:
      True if the target device is local; False if remote or not certain.
    """
    raise NotImplementedError

  @classmethod
  def PrepareLink(cls) -> None:
    """Setup prerequisites of device connections.

    Some device types need to do some setup before we can connect to.
    For example, we might need to start a DHCP server that assigns IP addresses
    to devices.
    """
    # Default to do nothing so leave it empty.


class DeviceComponent:
  """A base class for system components available on device.

  All modules under cros.factory.device (and usually a property of
  DeviceInterface) should inherit from DeviceComponent.

  Example::

  class MyComponent(DeviceComponent):

    @DeviceProperty
    def controller(self):
      return MyController(self)

    def SomeFunction(self):
      return self._do_something()

  Attributes:
    _device: A cros.factory.device.device_types.DeviceInterface instance for
             accessing target device.
    _dut: A legacy alias for _device.
    Error: Exception type for raising unexpected errors.
  """

  Error = DeviceException

  def __init__(self, device: 'DeviceInterface'):
    """Constructor of DeviceComponent.

    :type device: cros.factory.device.device_types.DeviceInterface
    """
    self._device = device


class DeviceInterface(abc.ABC, sys_interface.SystemInterface):
  """Abstract interface for accessing a device.

  This class provides an interface for accessing a device, for example reading
  its keyboard, turn on display, forcing charge state, forcing fan speeds, and
  reading temperature sensors.

  To obtain a :py:class:`cros.factory.device.device_types.DeviceInterface`
  object for the device under test, use the
  :py:func:`cros.factory.device.device_utils.CreateDUTInterface` function.

  Implementations of this interface should be in the
  :py:mod:`cros.factory.device.boards` package. Most Chromebook projects will
  inherit from :py:class:`cros.factory.device.boards.chromeos.ChromeOSBoard`.

  In general, this class is only for functionality that may need to be
  implemented separately on a board-by-board basis.  If there is a
  standard system-level interface available for certain functionality
  (e.g., using a Python API, a binary available on all boards, or
  ``/sys``) then it should not be in this class, but rather wrapped in
  a class in the :py:mod:`cros.factory.test.utils` module, or in a utility
  method in :py:mod:`cros.factory.utils`.  See
  :ref:`board-api-extending`.

  All methods may raise a :py:class:`DeviceException` on failure, or a
  :py:class:`NotImplementedError` if not implemented for this board.

  Attributes:
    link: A cros.factory.device.device_types.DeviceLink instance for accessing
          device.
  """

  def __init__(self, link: DeviceLink):
    """Constructor.

    Arg:
      link: A cros.factory.device.device_types.DeviceLink instance for accessing
            device.
    """
    super().__init__()
    self.link = link

  @DeviceProperty
  def accelerometer(self):
    """Sensor measures proper acceleration (also known as g-sensor)."""
    raise NotImplementedError

  @DeviceProperty
  def ambient_light_sensor(self):
    """Ambient light sensors."""
    raise NotImplementedError

  @DeviceProperty
  def audio(self):
    """Audio input and output, including headset, mic, and speakers."""
    raise NotImplementedError

  @DeviceProperty
  def bluetooth(self):
    """Interface to connect and control Bluetooth devices."""
    raise NotImplementedError

  @DeviceProperty
  def camera(self):
    """Interface to control camera devices."""
    raise NotImplementedError

  @DeviceProperty
  def display(self):
    """Interface for showing images or taking screenshot."""
    raise NotImplementedError

  @DeviceProperty
  def ec(self):
    """Module for controlling Embedded Controller."""
    raise NotImplementedError

  @DeviceProperty
  def fan(self):
    """Module for fan control."""
    raise NotImplementedError

  @DeviceProperty
  def gyroscope(self):
    """Gyroscope sensors."""
    raise NotImplementedError

  @DeviceProperty
  def hwmon(self):
    """Hardware monitor devices."""
    raise NotImplementedError

  @DeviceProperty
  def i2c(self):
    """Module for accessing to target devices on I2C bus."""
    raise NotImplementedError

  @DeviceProperty
  def info(self):
    """Module for static information about the system."""
    raise NotImplementedError

  @DeviceProperty
  def init(self):
    """Module for adding / removing start-up jobs."""
    raise NotImplementedError

  @DeviceProperty
  def led(self):
    """Module for controlling LED."""
    raise NotImplementedError

  @DeviceProperty
  def magnetometer(self):
    """Magnetometer / Compass."""
    raise NotImplementedError

  @DeviceProperty
  def memory(self):
    """Module for memory information."""
    raise NotImplementedError

  @DeviceProperty
  def partitions(self):
    """Provide information of partitions on a device."""
    raise NotImplementedError

  @DeviceProperty
  def path(self):
    """Provides operations on path names, similar to os.path."""
    raise NotImplementedError

  @DeviceProperty
  def power(self):
    """Interface for reading and controlling battery."""
    raise NotImplementedError

  @DeviceProperty
  def status(self):
    """Returns live system status (dynamic data like CPU loading)."""
    raise NotImplementedError

  @DeviceProperty
  def storage(self):
    """Information of the persistent storage on device."""
    raise NotImplementedError

  @DeviceProperty
  def temp(self):
    """Provides access to temporary files and directories."""
    raise NotImplementedError

  @DeviceProperty
  def thermal(self):
    """System module for thermal control (temperature sensors, fans)."""
    raise NotImplementedError

  @DeviceProperty
  def touch(self):
    """Module for touch."""
    raise NotImplementedError

  @DeviceProperty
  def toybox(self):
    """A python wrapper for http://www.landley.net/toybox/."""
    raise NotImplementedError

  @DeviceProperty
  def udev(self):
    """Module for detecting udev event."""
    raise NotImplementedError

  @DeviceProperty
  def usb_c(self):
    """System module for USB type-C."""
    raise NotImplementedError

  @DeviceProperty
  def vpd(self):
    """Interface for read / write Vital Product Data (VPD)."""
    raise NotImplementedError

  @DeviceProperty
  def vsync_sensor(self):
    """Camera vertical sync sensors."""
    return NotImplementedError

  @DeviceProperty
  def wifi(self):
    """Interface for controlling WiFi devices."""
    raise NotImplementedError

  @abc.abstractmethod
  def GetStartupMessages(self):
    """Get various startup messages.

    This is usually useful for debugging issues like unexpected reboot during
    test.

    Returns: a dict that contains logs.
    """
    raise NotImplementedError

  def IsReady(self):
    """Returns True if a device is ready for access.

    This is usually simply forwarded to ``link.IsReady()``, but some devices may
    need its own readiness check in additional to link layer.
    """
    return self.link.IsReady()


class DeviceBoard(DeviceInterface):
  """A base class all for board implementations to inherit from."""


class MockLink(DeviceLink):
  """A `DeviceLink` mocking class used for unittests."""

  @type_utils.Overrides
  def Push(self, local, remote):
    raise NotImplementedError

  @type_utils.Overrides
  def PushDirectory(self, local, remote):
    raise NotImplementedError

  @type_utils.Overrides
  def Pull(self, remote, local=None):
    raise NotImplementedError

  @type_utils.Overrides
  def PullDirectory(self, remote, local):
    raise NotImplementedError

  @type_utils.Overrides
  def Shell(self, command, stdin=None, stdout=None, stderr=None, cwd=None,
            encoding='utf-8'):
    raise NotImplementedError

  @type_utils.Overrides
  def IsReady(self):
    raise NotImplementedError

  @type_utils.Overrides
  def IsLocal(self):
    """In unittests we assume this is a remote device."""
    return False
