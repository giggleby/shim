# Copyright 2023 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.
"""An example pytest to show case how to save a CSV entry.

Description
-----------
This is an example pytest. The pytest calls ``csv_utils.CSVManager.Append`` to
store an entry on the device. This pytest doesn't need to have the internet
access.

Later in the factory flow, when running the sync_factory_server pytest, if
``upload_csv_entries`` is set, it uploads all previously recorded CSV entries to
the Google factory server.

Test Procedure
--------------
The test first do some measurements to collect data. Then call
``csv_utils.CSVManager.Append`` to store them.

Dependency
----------
Nothing special

Examples
--------
Here is a simple example::

  {
    "pytest_name": "record_csv_entry_example"
  },
  {
    "pytest_name": "sync_factory_server",
    "args": {
      "upload_csv_entries": true
    }
  }
"""

import random
import time

from cros.factory.test import test_case
from cros.factory.test.utils import csv_utils


class AddCsvEntry(test_case.TestCase):

  def runTest(self):
    csv_filename = 'hello_world'
    measurement = random.random()
    serial_number = 'SN12345'
    entry = [serial_number, measurement, time.time()]
    # This function will store the CSV entry locally.
    # The CSV entry will be sent to Google Factory Server on the next
    # sync_factory_server pytest.
    csv_utils.CSVManager().Append(csv_filename, entry)
