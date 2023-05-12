# Copyright 2023 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

from flask import Blueprint

from cros.factory.test_list_editor.backend.controller import test_list as test_list_controller
from cros.factory.test_list_editor.backend.middleware import validation
from cros.factory.test_list_editor.backend.models import files as files_model
from cros.factory.test_list_editor.backend.models import test_list as test_list_model
from cros.factory.test_list_editor.backend.schema import test_list as test_list_schema


def CreateBP():
  bp = Blueprint('tests', __name__, url_prefix='/api/v1/tests')

  factory = files_model.GetFactoryInstance()
  controller = test_list_controller.TestListController(factory)

  @bp.route('/<test_list_id>')
  @validation.Validate
  def GetTests(
      params: test_list_schema.TestSequenceParams
  ) -> test_list_schema.TestSequenceResponse:
    """Returns the test sequence of the give test list id."""
    return controller.GetTestSequence(params.test_list_id,
                                      test_list_model.TestList())

  @bp.route('/<test_list_id>', methods=['PUT'])
  @validation.Validate
  def UpdateTests(
      params: test_list_schema.TestSequenceParams,
      request_body: test_list_schema.TestSequenceRequest
  ) -> test_list_schema.TestSequenceResponse:
    """Returns the test sequence of the give test list id."""
    return controller.UpdateTestSequence(params.test_list_id,
                                         test_list_model.TestList(),
                                         request_body.data)

  return bp
