#!/usr/bin/env python3
#
# Copyright 2021 The Chromium OS Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.
"""Output decode HWID plugin.

A plugin to call HWID service API and decode HWID to component data.
"""

import time
import urllib

# pylint: disable=import-error, no-name-in-module
from google.auth import default
from google.auth.transport.requests import AuthorizedSession
from google.oauth2 import service_account

# pylint: enable=import-error, no-name-in-module
# isort: split
from cros.factory.instalog import datatypes
from cros.factory.instalog import plugin_base
from cros.factory.instalog.utils.arg_utils import Arg

_CHROMEOS_HWID_SCOPE = 'https://www.googleapis.com/auth/chromeoshwid'
_HWID_API_URL = 'https://chromeoshwid-pa.googleapis.com/v2/boms:batchGet'
_DEFAULT_INTERVAL = 10
# The BatchGetBom feature on HWID service cannot process more than 20 HWID in
# RPC deadline.
_DEFAULT_BATCH_SIZE = 20
_ALLOWED_PHASE = ['PVT', 'DVT', 'EVT', 'MP', 'RMA', 'PROTO']


class OutputDecodeHwid(plugin_base.OutputPlugin):

  ARGS = [
      Arg('interval', (int, float),
          'Frequency to call HWID decode service, in seconds.',
          default=_DEFAULT_INTERVAL),
      Arg('batch_size', int, 'How many HWID events to queue before decoding.',
          default=_DEFAULT_BATCH_SIZE),
      # TODO(chuntsen): Remove key_path argument since we don't use it anymore.
      Arg(
          'key_path', str,
          'Path to Cloud Storage service account JSON key file.  If set to '
          'None, the Google Cloud client will use the default service account '
          'which is set to the environment variable '
          'GOOGLE_APPLICATION_CREDENTIALS or Google Cloud services.',
          default=None),
  ]

  def __init__(self, *args, **kwargs):
    self.authed_session = None
    super().__init__(*args, **kwargs)

  def SetUp(self):
    """Builds the client object and the table object to run BigQuery calls."""
    if self.args.key_path:
      cred = service_account.Credentials.from_service_account_file(
          self.args.key_path, scopes=[_CHROMEOS_HWID_SCOPE])
    else:
      cred, _unused_project = default(scopes=[_CHROMEOS_HWID_SCOPE])
    self.authed_session = AuthorizedSession(cred)

  def Main(self):
    """Main thread of the plugin."""
    while not self.IsStopping():
      if not self.DecodeHwid():
        self.Sleep(1)

  def SendRequest(self, data):
    """Sends requests to HWID service."""
    headers = {
        'Content-Type': 'application/x-www-form-urlencoded',
        'X-HTTP-Method-Override': 'GET'
    }
    data = urllib.parse.urlencode(data, doseq=True)
    try:
      response = self.authed_session.post(_HWID_API_URL, data=data,
                                          headers=headers)
      if response.status_code == 200:
        return response.json()
      self.error('Data: %s, receive status: %d, content: %s', data,
                 response.status_code, response.content)
      return None
    except Exception:
      self.exception('Exception encountered')
      return None

  def ProcessBom(self, hwid, bom):
    """Processes responses from HWID service to Instalog Event."""
    event = datatypes.Event({})
    event['hwid'] = hwid
    event['time'] = time.time()
    event['phase'] = bom['phase']
    # The phase is set by partner, so it may have other prefix or suffix.
    # For example, 'EVT_xxx', 'PVE_2', and 'xxx-PVT'
    for phase in _ALLOWED_PHASE:
      if bom['phase'].startswith(phase) or bom['phase'].endswith(phase):
        event['phase'] = phase
    event['components'] = bom['components']
    event['__hwid__'] = True
    return event

  def DecodeHwid(self):
    """Call HWID service to decode HWIDs."""
    event_stream = self.NewStream()
    if not event_stream:
      return False

    event_count = 0
    hwids = set()
    for event in event_stream.iter(timeout=self.args.interval,
                                   count=self.args.batch_size):
      if 'hwid' in event:
        event_count += 1
        hwids.add(event['hwid'])

    if not hwids:
      event_stream.Commit()
      return True

    # Use verbose=True to get details of components.
    data = {
        'hwid': list(hwids),
        "verbose": True
    }

    # If we didn't receive response, we still call Commit() to avoid the plugin
    # suspend.
    response = self.SendRequest(data)

    events = []
    if response and response.get('boms', None):
      for hwid, bom in response['boms'].items():
        if bom:
          events.append(self.ProcessBom(hwid, bom))

    if self.Emit(events):
      self.info('Commit %d events, decode %d HWIDs', event_count, len(events))
      event_stream.Commit()
      return True
    event_stream.Abort()
    return False


if __name__ == '__main__':
  plugin_base.main()
