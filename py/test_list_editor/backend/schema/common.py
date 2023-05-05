# Copyright 2023 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.
from enum import Enum

from pydantic import BaseModel


class StatusEnum(str, Enum):
  """Enumeration for different status types."""

  SUCCESS = 'success'
  ERROR = 'error'
  VALIDATION_ERROR = 'validation_error'


class BaseResponse(BaseModel):
  """Base response class containing a status and a message.

  This class uses the Config class to forbid any extra fields. The setting
  can be overridden by defining it in inherited class.

  Attributes:
    status (StatusEnum): The status of the response.
    message (str): Optional message associated with the response.
  """
  status: StatusEnum
  message: str = ''

  # The Config class is used by Pydantic and the `forbid` value denies having
  # any fields than the defined ones.
  # ref: https://docs.pydantic.dev/usage/model_config/#options
  class Config:
    extra = 'forbid'


class BaseRequest(BaseModel):
  """Base request class with no extra fields.

  This class uses the Config class to forbid any extra fields. The setting
  can be overridden by defining it in inherited class.

  Attributes:
    N/A
  """

  # The Config class is used by Pydantic and the `forbid` value denies having
  # any fields other than the defined ones.
  # ref: https://docs.pydantic.dev/usage/model_config/#options
  class Config:
    extra = 'forbid'
