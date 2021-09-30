#!/usr/bin/env python3
#
# Copyright 2021 The Chromium OS Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.
"""Input GCS scan plugin.

A plugin to scan new files on Google Cloud Storage. After this plugin emit file
link to other plugins, it will record MD5 hash to avoid processing the same
file.
"""

import base64
import datetime
import itertools
import os

from cros.factory.instalog import datatypes
from cros.factory.instalog import json_utils
from cros.factory.instalog import plugin_base
from cros.factory.instalog.utils.arg_utils import Arg
from cros.factory.instalog.utils import file_utils
from cros.factory.instalog.utils import gcs_utils
from cros.factory.instalog.utils import time_utils


_DEFAULT_INTERVAL = 60


class InputGCSScan(plugin_base.InputPlugin):

  ARGS = [
      # TODO(chuntsen): Remove key_path argument since we don't use it anymore.
      Arg(
          'key_path', str,
          'Path to BigQuery/CloudStorage service account JSON key file.  If '
          'set to None, the Google Cloud client will use the default service '
          'account which is set to the environment variable '
          'GOOGLE_APPLICATION_CREDENTIALS or Google Cloud services.',
          default=None),
      Arg('bucket_id', str, 'Bucket ID to scan.'),
      Arg('blob_prefix', list, 'Blob prefix to match.', default=None),
      Arg('start_time', str, 'The start of datetime in isoformat to scan.',
          default='1970-01-01'),
      Arg('end_time', str, 'The end of datetime in isoformat to scan.',
          default='2100-12-31'),
      Arg('interval', (int, float), 'Interval in between scans, in seconds.',
          default=_DEFAULT_INTERVAL)
  ]

  def __init__(self, *args, **kwargs):
    self.gcs = None
    self.start_time = None
    self.end_time = None
    self.record_path = None
    super(InputGCSScan, self).__init__(*args, **kwargs)

  def SetUp(self):
    """Authenticates the connection to Cloud Storage."""
    self.gcs = gcs_utils.CloudStorage(self.args.key_path, self.logger)
    self.start_time = time_utils.DatetimeToUnixtime(
        datetime.datetime.strptime(self.args.start_time,
                                   json_utils.FORMAT_DATE))
    self.end_time = time_utils.DatetimeToUnixtime(
        datetime.datetime.strptime(self.args.end_time, json_utils.FORMAT_DATE))
    self.record_path = os.path.join(self.GetDataDir(), 'processed_blob')
    if not os.path.isfile(self.record_path):
      file_utils.TouchFile(self.record_path)

  def Main(self):
    """Main thread of the plugin."""
    while not self.IsStopping():
      self.ScanGCS()
      self.Sleep(self.args.interval)

  def ScanGCS(self):
    """Scans Google Cloud Storage and finds unprocessed files."""
    try:
      if not self.args.blob_prefix:
        all_blobs = self.gcs.client.list_blobs(self.args.bucket_id)
      else:
        all_blobs = itertools.chain(*[
            self.gcs.client.list_blobs(self.args.bucket_id, prefix=prefix)
            for prefix in self.args.blob_prefix
        ])

      blob_dict = {}
      for blob in all_blobs:
        if self.IsStopping():
          return

        blob_event = self.CreateBlobEvent(blob)
        if blob_event and blob_event['objectId'] not in blob_dict:
          blob_dict[blob_event['objectId']] = blob_event

      self.RemoveProcessedBlob(blob_dict)

      if blob_dict:
        self.info('Found %d new ReportArchives', len(blob_dict))
        events = list(blob_dict.values())
        if self.Emit(events):
          with file_utils.AtomicWrite(self.record_path) as f:
            f.write(file_utils.ReadFile(self.record_path))
            for event in events:
              f.write(event.Serialize() + '\n')
    except Exception:
      self.exception('Exception encountered during getting blobs')
      return

  def CreateBlobEvent(self, blob: gcs_utils.storage.Blob):
    """Checks the creation time of the blob.

    Returns a Event if the creation time is valid, or None otherwise"""
    object_id = None
    try:
      object_id = '/%s/%s' % (self.args.bucket_id, blob.name)
      if blob.time_created is None or blob.md5_hash is None:
        blob.reload()
      blob_hash = base64.standard_b64decode(blob.md5_hash).hex()
      blob_time = time_utils.DatetimeToUnixtime(blob.time_created)
      if self.start_time <= blob_time < self.end_time:
        return datatypes.Event({
            'objectId': object_id,
            'time': blob_time,
            'size': blob.size,
            'md5': blob_hash
        })
    except Exception:
      # If the GCS file an exception, we just skip this file and try again in
      # the next round.
      self.exception('Exception encountered during create blob event: %s',
                     object_id)
    return None

  def RemoveProcessedBlob(self, blob_dict):
    """Removes the processed blobs from blob_dict."""
    with open(self.record_path, 'r') as f:
      for line in f:
        blob_event = datatypes.Event.Deserialize(line)
        processed_object_id = blob_event['objectId']
        if processed_object_id in blob_dict:
          blob_dict.pop(processed_object_id)


if __name__ == '__main__':
  plugin_base.main()
