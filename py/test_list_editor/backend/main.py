# Copyright 2023 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

from flask import Flask

from cros.factory.test_list_editor.backend.api import status
from cros.factory.test_list_editor.backend.api.v1 import files
from cros.factory.test_list_editor.backend.api.v1 import items
from cros.factory.test_list_editor.backend.exceptions import config as config_exception
from cros.factory.test_list_editor.backend.middleware import validation_exception


def CreateApp():
  flask_app = Flask(__name__)
  flask_app.register_blueprint(status.bp)
  flask_app.register_blueprint(files.CreateBP())
  flask_app.register_blueprint(items.CreateBP())

  validation_exception.RegisterErrorHandler(flask_app)
  config_exception.RegisterErrorHandler(flask_app)
  return flask_app


app = CreateApp()
