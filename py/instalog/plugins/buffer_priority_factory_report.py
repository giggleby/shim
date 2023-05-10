#!/usr/bin/env python3
#
# Copyright 2022 The ChromiumOS Authors.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.
"""Priority multi-file-based factory report buffer."""

import datetime

from cros.factory.instalog import json_utils
from cros.factory.instalog import plugin_base
from cros.factory.instalog.plugins import buffer_priority_file
from cros.factory.utils import arg_utils
from cros.factory.utils.arg_utils import Arg
from cros.factory.utils import time_utils


DEFAULT_SEPARATE_TIME = '2022-01-01'


class BufferPriorityFactoryReport(buffer_priority_file.BufferPriorityFile):
  ARGS = arg_utils.MergeArgs(buffer_priority_file.BufferPriorityFile.ARGS, [
      Arg(
          'separate_time', str,
          'The time to separate the priority. The earlier events will have '
          'higher priority.', default=DEFAULT_SEPARATE_TIME)
  ])

  def __init__(self, *args, **kwargs):
    self.separate_time = None
    super().__init__(*args, **kwargs)

  def EventLevel(self, event):
    self.separate_time = time_utils.DatetimeToUnixtime(
        datetime.datetime.strptime(self.args.separate_time,
                                   json_utils.FORMAT_DATE))
    if event.get('__report__') is True:
      return 0
    if event.get('__process__') is True:
      return 1
    if 'time' in event and event.get('time') > self.separate_time:
      return 2
    return 3


if __name__ == '__main__':
  plugin_base.main()
