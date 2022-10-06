#!/usr/bin/env python3
# Copyright 2018 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""The service handler for APIs."""

import http
import logging

import flask
import google.cloud.logging as gc_logging
from google.cloud import tasks

# isort: split

from cros.factory.hwid.service.appengine import auth
from cros.factory.hwid.service.appengine.config import CONFIG
from cros.factory.hwid.service.appengine import hwid_api
from cros.factory.hwid.service.appengine import ingestion
from cros.factory.probe_info_service.app_engine import protorpc_utils


@auth.HttpCheck
def _CronJobHandler(service, method):
  del service, method  # Unused since we only rewrite the request path.
  client = tasks.CloudTasksClient()
  parent = client.queue_path(CONFIG.cloud_project, CONFIG.project_region,
                             CONFIG.queue_name)
  path = flask.request.path
  client.create_task(
      parent=parent, task={
          'app_engine_http_request': {
              'http_method': 'POST',
              'relative_uri': path.replace('/cron/', '/_ah/stubby/')
          }
      })
  return flask.Response(status=http.HTTPStatus.OK)


def _WarmupHandler():
  """Do nothing, just to ensure the request handler is ready."""
  return flask.Response(status=http.HTTPStatus.NO_CONTENT)


def _CreateApp():
  app = flask.Flask(__name__)
  app.url_map.strict_slashes = False

  app.route('/cron/<service>.<method>', methods=('GET', ))(_CronJobHandler)
  app.route('/_ah/warmup', methods=('GET', ))(_WarmupHandler)

  protorpc_utils.RegisterProtoRPCServiceToFlaskApp(app, '/_ah/stubby',
                                                   hwid_api.ProtoRPCService())
  protorpc_utils.RegisterProtoRPCServiceToFlaskApp(
      app, '/_ah/stubby', ingestion.ProtoRPCService.CreateInstance())
  return app


def _InitLogging():
  if CONFIG.cloud_project:  # in App Engine environment
    gc_logging.Client().setup_logging(log_level=logging.DEBUG)
    if CONFIG.env == 'staging':
      import googlecloudprofiler  # pylint: disable=import-error
      googlecloudprofiler.start(verbose=3)
  else:
    logging.basicConfig(level=logging.DEBUG)


_InitLogging()
hwid_service = _CreateApp()


if __name__ == '__main__':
  hwid_service.run(debug=True)
