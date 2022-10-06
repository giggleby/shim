# Copyright 2019 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

import http
import logging
import os

import flask
from google.cloud import logging as gc_logging

from cros.factory.probe_info_service.app_engine import admin_service
from cros.factory.probe_info_service.app_engine import config
from cros.factory.probe_info_service.app_engine import protorpc_utils
from cros.factory.probe_info_service.app_engine import stubby_handler


def _InitLogging():
  _config = config.Config()
  if _config.env_type == config.EnvType.LOCAL:
    logging.basicConfig(level=_config.log_level)
  else:
    gc_logging.Client().setup_logging(log_level=_config.log_level)


# Setup logging framework based on the environment as early as possible.
_InitLogging()


def _WarmupHandler():
  """Do nothing, just to ensure the request handler is ready."""
  return flask.Response(status=http.HTTPStatus.NO_CONTENT)


def _CreateApp():
  flask_app = flask.Flask(__name__)
  flask_app.route('/_ah/warmup', methods=('GET', ))(_WarmupHandler)
  protorpc_utils.RegisterProtoRPCServiceToFlaskApp(
      flask_app, '/_ah/stubby', stubby_handler.ProbeInfoService())
  protorpc_utils.RegisterProtoRPCServiceToFlaskApp(
      flask_app, '/_ah/stubby', admin_service.AdminServiceServerStub())
  return flask_app


app = _CreateApp()


# Start the server when this module is launched directly.
if __name__ == '__main__':
  app.run(host=os.environ.get('PROBE_INFO_SERVICE_HOST', 'localhost'),
          port=os.environ.get('PROBE_INFO_SERVICE_PORT', 8080),
          debug=True)
