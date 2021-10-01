#!/usr/bin/env python3
#
# Copyright 2021 The Chromium OS Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.
"""Input BigQuqery HWID plugin.

Subclasses InputBigQuery to query HWID data and process result.
"""

from cros.factory.instalog import datatypes
from cros.factory.instalog import plugin_base
from cros.factory.instalog.plugins import input_bigquery


class InputBigQueryHWID(input_bigquery.InputBigQuery):

  def GetQuery(self):
    """Returns a query to run."""
    return """
      SELECT
        DISTINCT hwid
      FROM
        `chromeos-factory.factory_report.report_events`
    """

  def ProcessRow(self, row):
    """Processes a row and returns events to emit."""
    hwid = row.get('hwid', None)
    if hwid:
      return datatypes.Event({'hwid': hwid})
    return None


if __name__ == '__main__':
  plugin_base.main()
