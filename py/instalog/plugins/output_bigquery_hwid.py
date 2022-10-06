#!/usr/bin/env python3
#
# Copyright 2021 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.
"""BigQuery upload output plugin.

Subclasses OutputBigQuery to create table rows for HWID events.
"""

import json

from google.cloud.bigquery.schema import SchemaField

from cros.factory.instalog import plugin_base
from cros.factory.instalog.plugins import output_bigquery


class OutputBigQueryHWID(output_bigquery.OutputBigQuery):

  def GetTableSchema(self):
    """Returns a list of fields in the table schema."""
    return [
        SchemaField('components', 'record', 'REPEATED', None, (
            SchemaField('componentClass', 'string', 'NULLABLE', None, ()),
            SchemaField('name', 'string', 'NULLABLE', None, ()),
            SchemaField('componentId', 'integer', 'NULLABLE', None, ()),
            SchemaField('qualificationId', 'integer', 'NULLABLE', None, ()),
            SchemaField('fields', 'record', 'REPEATED', None, (
                SchemaField('name', 'string', 'NULLABLE', None, ()),
                SchemaField('value', 'string', 'NULLABLE', None, ()),
            )),
        )),
        SchemaField('phase', 'string', 'REQUIRED', None, ()),
        SchemaField('hwid', 'string', 'REQUIRED', None, ()),
        SchemaField('time', 'timestamp', 'REQUIRED', None, ()),
    ]

  def ConvertEventToRow(self, event):
    """Converts an event to its corresponding BigQuery table row JSON string."""
    if not event.get('__hwid__', False):
      return None

    row = {}

    row['components'] = []
    for component_dict in event.get('components', []):
      row['components'].append({})
      row['components'][-1]['componentClass'] = component_dict.get(
          'componentClass')
      row['components'][-1]['name'] = component_dict.get('name')
      if component_dict.get('hasAvl', False):
        row['components'][-1]['componentId'] = component_dict.get(
            'avlInfo', {}).get('componentId')
        row['components'][-1]['qualificationId'] = component_dict.get(
            'avlInfo', {}).get('qualificationId')
      row['components'][-1]['fields'] = []
      for field in component_dict.get('fields', []):
        row['components'][-1]['fields'].append({})
        row['components'][-1]['fields'][-1]['name'] = field.get('name')
        row['components'][-1]['fields'][-1]['value'] = field.get('value')

    row['phase'] = event.get('phase')
    row['hwid'] = event.get('hwid')
    row['time'] = event.get('time')

    return json.dumps(row, allow_nan=False)


if __name__ == '__main__':
  plugin_base.main()
