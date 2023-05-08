# Copyright 2023 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.
import unittest

from flask import Flask

from cros.factory.test_list_editor.backend.exceptions import config
from cros.factory.test_list_editor.backend.schema import common
from cros.factory.utils import config_utils


class ErrorHandlerTestCase(unittest.TestCase):

  def setUp(self):
    self.app = Flask(__name__)

    @self.app.route('/', methods=['GET'])
    def Get():
      raise config_utils.ConfigNotFoundError("Config not found")

  def testHandleConfigNotFoundException(self):
    exception = config_utils.ConfigNotFoundError("Config not found")
    response, status_code = config.HandleConfigNotFoundException(exception)

    self.assertEqual(status_code, 422)
    self.assertEqual(response['status'], common.StatusEnum.ERROR)
    self.assertEqual(response['message'], str(exception))

  def testRegisterErrorHandler(self):
    config.RegisterErrorHandler(self.app)
    with self.app.test_client() as client:
      response = client.get('/')
      self.assertEqual(response.status_code, 422)
      self.assertEqual(response.get_json()['status'], common.StatusEnum.ERROR)
      self.assertEqual(response.get_json()['message'], "Config not found")


if __name__ == '__main__':
  unittest.main()
