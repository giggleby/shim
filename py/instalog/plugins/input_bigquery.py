#!/usr/bin/env python3
#
# Copyright 2021 The Chromium OS Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.
"""Input BigQuqery plugin.

A plugin to query data in BigQuery.
"""

from google.cloud import bigquery  # pylint: disable=no-name-in-module
from google.oauth2 import service_account

from cros.factory.instalog import datatypes
from cros.factory.instalog import plugin_base
from cros.factory.instalog.utils.arg_utils import Arg

_BIGQUERY_SCOPE = 'https://www.googleapis.com/auth/bigquery'
_DEFAULT_INTERVAL = 86400


class InputBigQuery(plugin_base.InputPlugin):

  ARGS = [
      # TODO(chuntsen): Remove key_path argument since we don't use it anymore.
      Arg(
          'key_path', str,
          'Path to Cloud Storage service account JSON key file.  If set to '
          'None, the Google Cloud client will use the default service account '
          'which is set to the environment variable '
          'GOOGLE_APPLICATION_CREDENTIALS or Google Cloud services.',
          default=None),
      Arg('interval', (int, float), 'Interval in between querys, in seconds.',
          default=_DEFAULT_INTERVAL),
  ]

  def __init__(self, *args, **kwargs):
    self.JOB_ID_PREFIX = None
    self.client = None
    super(InputBigQuery, self).__init__(*args, **kwargs)

  def SetUp(self):
    """Builds the client object and the table object to run BigQuery calls."""
    self.JOB_ID_PREFIX = 'instalog_' + self.__class__.__name__ + '_'
    self.client = self.BuildClient()

  def Main(self):
    """Main thread of the plugin."""
    while not self.IsStopping():
      if self.QueryAndProcess():
        self.Sleep(self.args.interval)
      self.Sleep(1)

  def BuildClient(self):
    """Builds a BigQuery client object."""
    if self.args.key_path:
      credentials = service_account.Credentials.from_service_account_file(
          self.args.key_path, scopes=[_BIGQUERY_SCOPE])
    else:
      credentials = None
    # Query doesn't need a project ID.
    return bigquery.Client(project=None, credentials=credentials)

  def GetQuery(self):
    """Returns a query to run."""
    raise NotImplementedError

  def ProcessRow(self, row):
    """Processes a row and returns a event to emit."""
    raise NotImplementedError

  def QueryAndProcess(self):
    """Runs the query and processes the result."""
    query = self.GetQuery()
    job = None
    try:
      self.info('Start query')
      job = self.client.query(query, job_id_prefix=self.JOB_ID_PREFIX)
      row_iter = job.result()
      self.info('Found %d rows', row_iter.total_rows)
      assert job.state == 'DONE', 'Query job is not done'

      events = []
      for row in row_iter:
        event = self.ProcessRow(row)
        if isinstance(event, datatypes.Event):
          events.append(event)
    except Exception:
      if job and hasattr(job, 'errors'):
        self.exception('Query failed with errors: %s', job.errors)
      else:
        self.exception('Query failed')
      return False

    if self.Emit(events):
      self.info('Emit %d events, and sleep %d seconds', len(events),
                self.args.interval)
      return True
    return False
