# Copyright 2023 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.
#
# TODO(b/259232166): Add a unit test for this file.

import functools
from typing import Callable, List

import flask


class AllowlistException(Exception):
  pass


def Allowlist(allowed_loas_peer_usernames: List[str]) -> Callable:
  """Returns a allowlist decorator.

  Returns a decorator which only accepts the specific LOAS peer names to access
  an App Engine rpc call.  If a LOAS peer name isn't allowed to access, it
  raises an `AllowlistException`.

  Args:
    allowed_loas_peer_usernames: A list of strings which represents the allowed
        LOAS peer names.

  Returns:
    A function which can be used as a decorator.
  """

  def Decorator(function: Callable) -> Callable:

    @functools.wraps(function)
    def Wrapper(*args, **kwargs):
      loas_peer_username = flask.request.headers.get(
          'X-Appengine-Loas-Peer-Username')
      if loas_peer_username not in allowed_loas_peer_usernames:
        raise AllowlistException(
            f'LOAS_PEER_USERNAME {loas_peer_username} is not allowed')
      return function(*args, **kwargs)

    return Wrapper

  return Decorator
