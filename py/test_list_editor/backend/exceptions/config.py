# Copyright 2023 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.
from flask import Flask

from cros.factory.test_list_editor.backend.schema import common
from cros.factory.utils import config_utils


def HandleConfigNotFoundException(exception: config_utils.ConfigNotFoundError):
  """Handler for exception raised when config not found."""
  return common.BaseResponse(status=common.StatusEnum.ERROR,
                             message=str(exception)).dict(), 422


def RegisterErrorHandler(flask_app: Flask):
  flask_app.register_error_handler(config_utils.ConfigNotFoundError,
                                   HandleConfigNotFoundException)
