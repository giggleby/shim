#!/usr/bin/env python3
#
# Copyright 2023 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.
"""Output CSV reader plugin.

A plugin to parse CSV file to events.
"""

import csv
import datetime
import os

from cros.factory.instalog import datatypes
from cros.factory.instalog import plugin_base
from cros.factory.utils.arg_utils import Arg
from cros.factory.utils import gcs_utils
from cros.factory.utils import time_utils


_DEFAULT_INTERVAL = 60
_DEFAULT_BATCH_SIZE = 100


class OutputCSVReader(plugin_base.OutputPlugin):

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
      Arg(
          'impersonated_account', str,
          'A service account to impersonate.  The default credential should '
          'have the permission to impersonate the service account.  '
          '(roles/iam.serviceAccountTokenCreator)', default=None),
  ]

  def __init__(self, *args, **kwargs):
    self.gcs = None
    super().__init__(*args, **kwargs)

  def SetUp(self):
    self.gcs = gcs_utils.CloudStorage(
        json_key_path=self.args.key_path, logger=self.logger,
        impersonated_account=self.args.impersonated_account)

  def Main(self):
    """Main thread of the plugin."""
    while not self.IsStopping():
      if not self.DownloadAndProcessCSV():
        self.Sleep(1)

  def DownloadAndProcessCSV(self):
    """Downloads CSV files from Storage and processes them."""
    event_stream = self.NewStream()
    if not event_stream:
      return False

    csv_events = []
    for event in event_stream.iter(count=self.args.batch_size):
      object_id = event.get('objectId', '')
      if not object_id.lower().endswith('.csv'):
        continue
      self.info('Parsing CSV file: %s', object_id)
      csv_path = os.path.join(self.GetDataDir(), 'temp.csv')
      try:
        self.gcs.DownloadFile(object_id, csv_path, overwrite=True)
        csv_events.extend(self.ReadCSV(csv_path, object_id))
      except Exception:
        self.exception('Failed to parse the file: %s', object_id)
      finally:
        if os.path.exists(csv_path):
          os.unlink(csv_path)

    if self.Emit(csv_events):
      if csv_events:
        self.info('Commit %d events', len(csv_events))
      event_stream.Commit()
      return True
    event_stream.Abort()
    return False

  def ReadCSV(self, csv_path, object_id):
    """Reads CSV files and converts to events."""
    csv_events = []
    # Some CSV files have byte order mark, so we use 'utf-8-sig' here
    with open(csv_path, 'r', encoding='utf-8-sig') as f:
      reader = csv.reader(f)
      for row in reader:
        if len(row) != 3:
          self.warning('Doesn\'t have exactly 3 columns (%d)', len(row))
          return []
        if row == ['serial_number', 'hwid', 'timestamp']:
          continue
        try:
          # To parse no leading zeros format, we don't use fromisoformat()
          timestamp = datetime.datetime.strptime(row[2], '%Y-%m-%dT%H:%M:%S%z')
        except ValueError:
          self.exception('Failed to parse the timestamp: \'%s\'', row[2])
          return []
        unixtime = time_utils.DatetimeToUnixtime(timestamp)
        event = datatypes.Event({
            '__csv__': True,
            'objectId': object_id,
            'serialNumber': row[0],
            'hwid': row[1],
            'time': unixtime
        })
        csv_events.append(event)
    self.info('Found %d data', len(csv_events))
    return csv_events


if __name__ == '__main__':
  plugin_base.main()
