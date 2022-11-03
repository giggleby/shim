# Copyright 2022 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

import datetime
import os
from typing import List

from cros.factory.instalog import datatypes


def CreateSimpleEvents(num: int) -> List[datatypes.Event]:
  return [datatypes.Event({'num': i}) for i in range(num)]


def CreateEvents(num_events: int, num_attachments_per_event: int,
                 attachment_size: int, tmp_dir: str) -> List[datatypes.Event]:
  events = []
  for i in range(num_events):
    # Create fake attachment files for the event.
    attachments = {}
    for j in range(num_attachments_per_event):
      attachment_path = os.path.join(tmp_dir, f'{i:d}_{j:d}')
      with open(attachment_path, 'wb') as f:
        f.write(os.urandom(attachment_size))
      attachments[j] = attachment_path

    # Data for the event.
    data = {
        'name': 'instalog_benchmark',
        'id': i,
        'timestamp': datetime.datetime.now()
    }

    # Create the event.
    events.append(datatypes.Event(data, attachments))
  return events
