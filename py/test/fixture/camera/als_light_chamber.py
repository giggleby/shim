# Copyright 2014 The Chromium OS Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.


class ALSLightChamberError(Exception):
  pass


class ALSLightChamber(object):
  """The interface of ALS light chamber fixture."""

  def __init__(self, fixture_conn, fixture_cmd, retries=3):
    """Initializes ALSLightChamber.

    Args:
      fixture_conn: A FixtureConnection instance for controlling the fixture.
      fixture_cmd: A mapping between light name and a list of tuple
                   (cmd, response) required to activate the light.
    """
    self._fixture_conn = fixture_conn
    self._fixture_cmd = fixture_cmd
    self._retries = retries

  def Connect(self):
    self._fixture_conn.Connect()

  def SetLight(self, name, response=None):
    """Sets light through fixture connection.

    Args:
      name: name of light specified in fixture_cmd.
    """
    for unused_i in range(self._retries):
      for cmd, response in self._fixture_cmd[name]:
        ret = self._fixture_conn.Send(cmd, True)
        if response is None or ret.strip() == response:
          return

    raise ALSLightChamberError('SetLight: fixture fault')
