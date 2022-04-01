# Copyright 2021 The Chromium OS Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.
"""Shared utilities for all hwid_api related modules."""

import re

# pylint: disable=import-error, no-name-in-module
from cros.factory.hwid.service.appengine.proto import hwid_api_messages_pb2
# pylint: enable=import-error, no-name-in-module
from cros.factory.probe_info_service.app_engine import protorpc_utils

_KNOWN_BAD_HWIDS = ['DUMMY_HWID', 'dummy_hwid']
_KNOWN_BAD_SUBSTR = [
    '.*TEST.*', '.*CHEETS.*', '^SAMS .*', '.* DEV$', '.*DOGFOOD.*'
]


def FastFailKnownBadHWID(hwid):
  if hwid in _KNOWN_BAD_HWIDS:
    return (hwid_api_messages_pb2.Status.KNOWN_BAD_HWID,
            f'No metadata present for the requested project: {hwid}')

  for regexp in _KNOWN_BAD_SUBSTR:
    if re.search(regexp, hwid):
      return (hwid_api_messages_pb2.Status.KNOWN_BAD_HWID,
              f'No metadata present for the requested project: {hwid}')

  return (hwid_api_messages_pb2.Status.SUCCESS, '')


def ConvertExceptionToStatus(ex):
  if isinstance(ex, KeyError):
    return hwid_api_messages_pb2.Status.NOT_FOUND
  if isinstance(ex, ValueError):
    return hwid_api_messages_pb2.Status.BAD_REQUEST
  return hwid_api_messages_pb2.Status.SERVER_ERROR


def ConvertExceptionToProtoRPCException(ex):
  if isinstance(ex, KeyError):
    return protorpc_utils.ProtoRPCException(
        protorpc_utils.RPCCanonicalErrorCode.NOT_FOUND, str(ex))
  if isinstance(ex, ValueError):
    return protorpc_utils.ProtoRPCException(
        protorpc_utils.RPCCanonicalErrorCode.INVALID_ARGUMENT, str(ex))
  if isinstance(ex, NotImplementedError):
    return protorpc_utils.ProtoRPCException(
        protorpc_utils.RPCCanonicalErrorCode.UNIMPLEMENTED, str(ex))
  return protorpc_utils.ProtoRPCException(
      protorpc_utils.RPCCanonicalErrorCode.INTERNAL, str(ex))
