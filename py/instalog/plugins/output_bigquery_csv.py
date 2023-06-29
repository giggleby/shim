#!/usr/bin/env python3
#
# Copyright 2023 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.
"""BigQuery upload output plugin.

Subclasses OutputBigQuery to create table rows for CSV events.
"""

import json

from google.cloud.bigquery.schema import SchemaField

from cros.factory.instalog import plugin_base
from cros.factory.instalog.plugins import output_bigquery


class OutputBigQueryCSV(output_bigquery.OutputBigQuery):

  def GetTableSchema(self):
    """Returns a list of fields in the table schema."""
    return [
        SchemaField('objectId', 'string', 'REQUIRED', None, ()),
        SchemaField('serialNumber', 'string', 'REQUIRED', None, ()),
        SchemaField('hwid', 'string', 'REQUIRED', None, ()),
        SchemaField('time', 'timestamp', 'REQUIRED', None, ()),
    ]

  def ConvertEventToRow(self, event):
    """Converts an event to its corresponding BigQuery table row JSON string."""
    if not event.get('__csv__', False):
      return None

    row = {}

    row['objectId'] = event.get('objectId')
    row['serialNumber'] = event.get('serialNumber')
    row['hwid'] = event.get('hwid')
    row['time'] = event.get('time')

    return json.dumps(row, allow_nan=False)


if __name__ == '__main__':
  plugin_base.main()
