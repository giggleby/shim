# Copyright 2023 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

from flask import Flask

from cros.factory.test_list_editor.backend.schema import common


class ValidationException(Exception):
  """Base class for all validation exceptions."""

  def __init__(self, message):
    super().__init__(message)
    self.message = message


class ParamsValidationException(ValidationException):
  """Exception raised for parameters validation errors."""


class RequestValidationException(ValidationException):
  """Exception raised for request validation errors."""


class ResponseValidationException(ValidationException):
  """Exception raised for response validation errors."""


def HandleRequestValidationException(exception: ValidationException):
  return common.BaseResponse(status=common.StatusEnum.VALIDATION_ERROR,
                             message=str(exception.message)).dict(), 422


def HandleResponseValidationException(exception: ValidationException):
  return common.BaseResponse(status=common.StatusEnum.VALIDATION_ERROR,
                             message=str(exception.message)).dict(), 500


def RegisterErrorHandler(flask_app: Flask):
  flask_app.register_error_handler(ParamsValidationException,
                                   HandleRequestValidationException)
  flask_app.register_error_handler(RequestValidationException,
                                   HandleRequestValidationException)
  flask_app.register_error_handler(ResponseValidationException,
                                   HandleResponseValidationException)
