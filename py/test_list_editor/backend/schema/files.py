# Copyright 2023 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.
from typing import Any, Dict, List

from jsonschema import ValidationError as JSONValidationError
from pydantic import validator

from cros.factory.test.test_lists import test_list_common
from cros.factory.test_list_editor.backend.schema import common


class FileObject(common.BaseRequest):
  """Represents a file object.

  Attributes:
    filename (str): The name of the file.
    data (Dict[str, Any]): The content of the file as a dictionary.
  """
  filename: str
  data: Dict[str, Any]

  @validator('data')
  def ValidateTestList(cls, v):  # pylint:disable=no-self-argument
    """Validates the test list file schema.

    This method validates the schema of the test list file using the
    `test_list_common.ValidateTestListFileSchema` method and raises a
    `ValueError` if the validation fails.

    This function has to be a class method according to the documents from
    [Pydantic](https://docs.pydantic.dev/latest/usage/validators/)

    Args:
      cls: The class object.
      v: The value to validate.

    Returns:
      The validated value.

    Raises:
      ValueError: If the validation fails.
    """
    try:
      test_list_common.ValidateTestListFileSchema(v)
    except JSONValidationError as e:
      raise ValueError(e.message) from e
    return v


class FilesRequest(common.BaseRequest):
  """Represents a request to save a list of files.

  Attributes:
    files (List[FileObject]): The list of files to save.
  """
  files: List[FileObject]


class FileResponse(common.BaseResponse):
  """Represents a response for a file object.

  This class inherits from the `common.BaseResponse` class.
  """


class SaveFilesResponse(common.BaseResponse):
  """Represents a response for a list of saved files.

  Attributes:
    file_status (Dict[str, FileResponse]): The status of each file in the
      request.
  """
  file_status: Dict[str, FileResponse] = {}
