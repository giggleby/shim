# Copyright 2023 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.
"""A decorator middleware for validating request and response.

The `Validate` function can be used as a decorator to validate the parameters
and the request body of a Flask route function using Pydantic models. If the
validation fails, an error response with a 422 status code is returned. If the
validation succeeds, the wrapped function is called, and its result is
validated against the specified return type.

You can use the decorator like the following.

```python
@app.route('/foo')
@Validate
def Function(...):
  ...
```

To use the decorator to perform data validation, you should add type hintings
to the wrapped function. The decorator will look at the type
hints of `params`, `request_body` and return type. It will use these three
types to validate the corresponding data. See below example.

Examples:
```python

class UserIDParam(BaseModel):
  user_id: int

class UserData(BaseModel):
  name: str

class UserResponse(BaseModel):
  user_id: int
  name: str

@app.route('/users/<user_id>', methods=['POST'])
@Validate
def CreateUser(params: UserIDParam, request_body: UserData) -> UserResponse:

  assert isinstance(params.user_id, int)
```
"""

from functools import wraps
import typing
from typing import Type

from flask import request
from pydantic import BaseModel
from pydantic import ValidationError

from cros.factory.test_list_editor.backend.middleware import validation_exception as exceptions


_PARAMS_STR = 'params'
_REQUEST_STR = 'request_body'
_RESPONSE_STR = 'return'


def _MarshalData(model: Type[BaseModel], data: dict) -> BaseModel:
  return model(**data)


def _ValidateDataWithModels(
    data_model: Type[BaseModel], data: dict,
    model_exception: Type[exceptions.ValidationException]):
  """Validates data using Pydantic models.

  This function validates the given data using a Pydantic model specified as
  `data_model`. If validation succeeds, the validated data is returned. If
  validation fails, a `model_exception` is raised with the error message.

  Args:
    data_model: A Pydantic model used for validating the data.
    data: The data to be validated, provided as a dictionary.
    model_exception: The exception class to be raised in case of
      validation failure. This should be a class derived from
      exceptions.ValidationException.

  Returns:
      The validated data.

  Raises:
      ValidationException: If the data fails validation.

  """
  try:
    return _MarshalData(data_model, data)
  except ValidationError as e:
    raise model_exception(str(e)) from e


def Validate(f):
  """Decorator function for validating request and response.

  This decorator function validates the incoming request's parameters, request
  body using Pydantic models specified in the function's type hints.

  If validation succeeds, the wrapped function is called with the validated
  parameters and request body. If validation fails, the function returns an
  error response with a validation error message.

  Args:
    f: A function to be wrapped.

  Returns:
    A wrapper function that validates the incoming request's parameters, request
      body and response.
  """
  hints = typing.get_type_hints(f)

  @wraps(f)
  def wrapped(*args, **kwargs):  # pylint: disable=unused-argument
    func_kwargs = {}
    if _PARAMS_STR in hints:
      func_kwargs[_PARAMS_STR] = _ValidateDataWithModels(
          hints[_PARAMS_STR], request.view_args,
          exceptions.ParamsValidationException)
    if _REQUEST_STR in hints:
      func_kwargs[_REQUEST_STR] = _ValidateDataWithModels(
          hints[_REQUEST_STR], request.get_json(),
          exceptions.RequestValidationException)

    result: BaseModel = f(**func_kwargs)
    result_data = _ValidateDataWithModels(
        hints[_RESPONSE_STR], result.dict(),
        exceptions.ResponseValidationException)
    return result_data.dict()

  return wrapped
