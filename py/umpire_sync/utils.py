# Copyright 2021 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

import enum

from cros.factory.utils import json_utils


class Status(str, enum.Enum):
  Waiting = 'Waiting'
  Updating = 'Updating'
  Success = 'Success'
  Failure = 'Failure'

  def __str__(self):
    return self.name


class StatusUpdater:

  def __init__(self, status_path):
    self.status_path = status_path
    self.status_dict = {}

  def SetStatus(self, url, status, update_timestamp=None):
    timestamp = ''
    if update_timestamp:
      timestamp = update_timestamp
    elif url in self.status_dict:
      timestamp = self.status_dict[url]['update_timestamp']

    self.status_dict[url] = {
        'status': status,
        'update_timestamp': timestamp
    }
    json_utils.DumpFile(self.status_path, self.status_dict)
