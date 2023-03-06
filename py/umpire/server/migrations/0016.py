# Copyright 2023 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

import json
import os
import uuid

# Private constants.
_PROPERTIES_DIR = '/var/db/factory/umpire/properties'
_REPORT_FILEPATH = os.path.join(_PROPERTIES_DIR, 'report_index.json')


def Migrate():
  if not os.path.exists(_PROPERTIES_DIR):
    os.mkdir(_PROPERTIES_DIR)

  with open(_REPORT_FILEPATH, 'w', encoding='utf8') as json_file:
    json_file.write(json.dumps({
      'server_uuid': str(uuid.uuid4()),  # Create a new server uuid first.
      'next_report_index': 1  # The report index will start from 1.
    }, indent=2, separators=(',', ': '), sort_keys=True) + '\n')
