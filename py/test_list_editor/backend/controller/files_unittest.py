# Copyright 2023 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

import unittest
from unittest import mock

from cros.factory.test_list_editor.backend.controller import files as file_controller
from cros.factory.test_list_editor.backend.schema import common as common_schema


class TestFilesController(unittest.TestCase):

  def setUp(self) -> None:
    self.file_factory_mock = mock.Mock()
    self.file_mock = mock.Mock()
    self.file_factory_mock.Get.return_value = self.file_mock
    self.file_controller = file_controller.SaveFileController(
        self.file_factory_mock)

  def testValidateAllFiles(self):
    files_request = mock.Mock()
    files_request.files = [
        mock.Mock(filename='foo1.txt', data={}),
        mock.Mock(filename='foo2.txt', data={})
    ]
    controller = file_controller.SaveFileController(self.file_factory_mock)
    response = controller.SaveFiles(files_request)

    self.assertEqual(response.status, common_schema.StatusEnum.SUCCESS)
