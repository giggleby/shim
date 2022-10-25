# Copyright 2012 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

import base64
import binascii
import logging
import re
import struct

from cros.factory.proto import reg_code_pb2
from cros.factory.proto.reg_code_pb2 import RegCode
from cros.factory.utils import type_utils


# Registration code length in characters.
LEGACY_REGISTRATION_CODE_LENGTH = 72

# New-style registration code payload length, in bytes.
REGISTRATION_CODE_PAYLOAD_BYTES = 32


# Pattern matching devices in reg code.
DEVICE_PATTERN = re.compile(r'^\w+(?:-\w+)?$')


class RegistrationCodeException(Exception):
  pass


class RegistrationCode:
  """A registration code.

  Properties:
    encoded_string: The encoded registration code.
    type: The type of code (a member of the Type enum).
    device: The device type, if known.
  """

  Type = type_utils.Enum(['UNIQUE_CODE', 'GROUP_CODE', 'ONE_TIME_CODE',
                          'LEGACY'])
  """Registration code type.

  - UNIQUE_CODE: A unique user code (ubind_attribute value).
  - GROUP_CODE: A group code (gbind_attribute value).
  - ONE_TIME_CODE: A code for one-time use only.  Not likely to be seen
    in the factory.
  - LEGACY: A legacy (72-character) ubind_attribute or gbind_attribute value.
    There is no way to distinguish unique and group codes in the old format.
  """

  def __init__(self, encoded_string):
    """Parses a registration code.

    This may either be:

    - the legacy 72-character representation, or
    - the protobuf-based representation, beginning with an equals sign

    Args:
      encoded_string: The encoded registration code string.

    Raises:
      RegistrationCodeException: If the registration code is invalid.
    """
    self.encoded_string = encoded_string

    if encoded_string[0] == '=':
      # New representation, note that this function does not accept unicode
      # string so we need to convert the input back to a ASCII string
      data = base64.urlsafe_b64decode(str(encoded_string[1:]))

      # Make sure that it encodes back to the same thing (e.g., no extra
      # padding)
      expected_encoded_string = '=' + base64.urlsafe_b64encode(
          data).strip().decode('utf-8')
      if encoded_string != expected_encoded_string:
        raise RegistrationCodeException(
            f'Reg code {encoded_string!r} has bad base64 encoding (should be '
            f'{expected_encoded_string!r})')

      self.proto = RegCode()
      self.proto.ParseFromString(data)
      if len(self.proto.content.code) != REGISTRATION_CODE_PAYLOAD_BYTES:
        raise RegistrationCodeException(
            f'In reg code {encoded_string!r}, expected '
            f'{int(REGISTRATION_CODE_PAYLOAD_BYTES)}-byte code but got '
            f'{len(self.proto.content.code)} bytes')

      expected_checksum = (
          binascii.crc32(self.proto.content.SerializeToString()) & 0xFFFFFFFF)
      if expected_checksum != self.proto.checksum:
        raise RegistrationCodeException(
            f'In reg code {encoded_string!r}, expected checksum 0x'
            f'{self.proto.checksum:x} but got 0x{expected_checksum:x}')

      self.type = {
          reg_code_pb2.UNIQUE_CODE: RegistrationCode.Type.UNIQUE_CODE,
          reg_code_pb2.GROUP_CODE: RegistrationCode.Type.GROUP_CODE,
          reg_code_pb2.ONE_TIME_CODE: RegistrationCode.Type.ONE_TIME_CODE
      }.get(self.proto.content.code_type)
      if self.type is None:
        raise RegistrationCodeException(
            f'In reg code {encoded_string!r}, unexpected code type')

      self.device = (
          str(self.proto.content.device)
          if self.proto.content.HasField('device') else None)
      if self.type != RegistrationCode.Type.ONE_TIME_CODE:
        if self.device is None:
          raise RegistrationCodeException(
              f'In reg code {encoded_string!r}, expected non-empty device')

      if self.device is not None and not DEVICE_PATTERN.match(self.device):
        raise RegistrationCodeException(
            f'In reg code {encoded_string!r}, invalid device {self.device!r} '
            f'(expected pattern {DEVICE_PATTERN.pattern!r})')
    elif len(encoded_string) == LEGACY_REGISTRATION_CODE_LENGTH:
      # Old representation
      CheckLegacyRegistrationCode(encoded_string)
      self.type = RegistrationCode.Type.LEGACY
      self.device = None
      self.proto = None
    else:
      raise RegistrationCodeException(
          f'Invalid registration code {encoded_string!r}')

  def __str__(self):
    return (f'RegistrationCode(type={self.type!r}, device={self.device!r}, '
            f'encoded_string={self.encoded_string!r})')


def CheckLegacyRegistrationCode(code):
  """Checks that a legacy registration code is valid.

  Args:
    code: The registration code to check.

  Raises:
    RegistrationCodeException: If the registration code is invalid.
  """
  if len(code) != LEGACY_REGISTRATION_CODE_LENGTH:
    raise RegistrationCodeException(
        f'Registration code {code!r} is not '
        f'{int(LEGACY_REGISTRATION_CODE_LENGTH)} characters long')
  if re.search('[^0-9a-f]', code):
    raise RegistrationCodeException(
        f'Registration code {code!r} has invalid characters')

  # Parse payload and CRC as byte strings.
  payload = binascii.unhexlify(code[0:64])
  crc = binascii.unhexlify(code[64:72])
  expected_crc = struct.pack('!I', binascii.crc32(payload) & 0xFFFFFFFF)
  if expected_crc != crc:
    raise RegistrationCodeException(f'CRC of {code!r} is invalid (should be '
                                    f'{binascii.hexlify(expected_crc)})')


# pylint: disable=redefined-builtin
def CheckRegistrationCode(encoded_string, type=None, device=None,
                          allow_dummy=False):
  """Checks that a registration code is valid.

  Args:
    encoded_string: The registration code to check (either new-style or
        old-style).
    type: The required type, if any.  A member of the RegistrationCode.Type
        enum.  This is ignored for legacy registration codes.
    device: The required device, if any.  A member of the
        RegistrationCode.Type enum.  This is ignored for legacy registration
        codes.

  Raises:
    RegistrationCodeException: If the registration code is invalid or does
        not match the required type or device.
  """
  # Check if this is dummy regcode. See b/117463731.
  if '__TESTING__' in encoded_string:
    if allow_dummy:
      logging.warning('Registration code %r is dummy.', encoded_string)
    else:
      raise RegistrationCodeException(
          f'Registration code {encoded_string!r} is dummy')

  reg_code = RegistrationCode(encoded_string)
  if (type and reg_code.type != RegistrationCode.Type.LEGACY and
      reg_code.type != type):
    raise RegistrationCodeException(
        f'In code {encoded_string!r}, expected type {type!r} but got '
        f'{reg_code.type!r}')
  if (device and reg_code.type != RegistrationCode.Type.LEGACY and
      reg_code.device != device):
    raise RegistrationCodeException(
        f'In code {encoded_string!r}, expected device {device!r} but got '
        f'{reg_code.device!r}')
