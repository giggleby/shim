#!/usr/bin/env python3
# Copyright 2023 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.
import unittest

from flask import Flask
from pydantic import BaseModel

from cros.factory.test_list_editor.backend.middleware import validation
from cros.factory.test_list_editor.backend.middleware import validation_exception
from cros.factory.test_list_editor.backend.schema import common


class TestValidateParams(unittest.TestCase):

  def setUp(self) -> None:
    self.app = Flask(__name__)

    class UserIDParam(BaseModel):
      user_id: int

    class UserResponse(BaseModel):
      user_id: int

    @self.app.route('/users/<user_id>', methods=['GET'])
    @validation.Validate
    def GetUser(params: UserIDParam) -> UserResponse:
      return UserResponse(user_id=params.user_id)

    class UserResourceParam(BaseModel):
      user_id: int
      file_name: str

    class UserResourceResponse(BaseModel):
      user_id: int
      file_name: str

    @self.app.route('/users/<user_id>/file/<file_name>', methods=['GET'])
    @validation.Validate
    def GetUserFile(params: UserResourceParam) -> UserResourceResponse:
      return UserResourceResponse(user_id=params.user_id,
                                  file_name=params.file_name)

    validation_exception.RegisterErrorHandler(self.app)

  def testValidParams(self):
    with self.app.test_client() as client:
      response = client.get('/users/123')
      self.assertEqual(response.status_code, 200)
      self.assertEqual(response.get_json(), {'user_id': 123})

  def testMultipleValidParams(self):
    with self.app.test_client() as client:
      response = client.get('/users/123/file/foo.txt')
      self.assertEqual(response.status_code, 200)
      self.assertEqual(response.get_json(), {
          'user_id': 123,
          'file_name': 'foo.txt'
      })

  def testInvalidParams(self):
    with self.app.test_client() as client:
      response = client.get('/users/abc')
      self.assertEqual(response.status_code, 422)
      self.assertEqual(response.get_json()['status'],
                       common.StatusEnum.VALIDATION_ERROR)


class TestValidateRequest(unittest.TestCase):

  def setUp(self) -> None:
    self.app = Flask(__name__)

    class UserRequest(BaseModel):
      user_id: int

    class UserResponse(BaseModel):
      user_id: int

    @self.app.route('/users/', methods=['GET'])
    @validation.Validate
    def CreateUser(request_body: UserRequest) -> UserResponse:  # pylint: disable=unused-argument
      return UserResponse(user_id=123)

    validation_exception.RegisterErrorHandler(self.app)

  def testValidRequestBody(self):
    with self.app.test_client() as client:
      response = client.get('/users/', json={'user_id': 123})
      self.assertEqual(response.status_code, 200)
      self.assertEqual(response.get_json(), {'user_id': 123})

  def testInvalidRequestBody(self):
    with self.app.test_client() as client:
      response = client.get('/users/', json={'user_id': 'abc'})
      self.assertEqual(response.status_code, 422)
      self.assertEqual(response.get_json()['status'],
                       common.StatusEnum.VALIDATION_ERROR)


class TestValidateResponse(unittest.TestCase):

  def setUp(self) -> None:
    self.app = Flask(__name__)

    validation_exception.RegisterErrorHandler(self.app)

  def testValidResponse(self):

    class UserResponse(BaseModel):
      user_id: int

    @self.app.route('/users/', methods=['GET'])
    @validation.Validate
    def CreateUser() -> UserResponse:
      return UserResponse(user_id=123)

    with self.app.test_client() as client:
      response = client.get('/users/')
      self.assertEqual(response.status_code, 200)
      self.assertEqual(response.get_json(), {'user_id': 123})

  def testValidResponseDifferentClass(self):

    class UserResponse(BaseModel):
      user_id: int

    class AnotherUserResponse(BaseModel):
      user_id: int

    @self.app.route('/users/', methods=['GET'])
    @validation.Validate
    def GetUser() -> UserResponse:
      return AnotherUserResponse(user_id=123)

    with self.app.test_client() as client:
      response = client.get('/users/')
      self.assertEqual(response.status_code, 200)
      self.assertEqual(response.get_json(), {'user_id': 123})

  def testInvalidResponse(self):

    class UserResponse(BaseModel):
      user_id: int

    class BadUserResponse(BaseModel):
      user_id: str

    @self.app.route('/users/', methods=['GET'])
    @validation.Validate
    def CreateUser() -> UserResponse:
      return BadUserResponse(user_id='abc')

    with self.app.test_client() as client:
      response = client.get('/users/')
      self.assertEqual(response.status_code, 500)
      self.assertEqual(response.get_json()['status'],
                       common.StatusEnum.VALIDATION_ERROR)


class TestCombinedUsecase(unittest.TestCase):

  def setUp(self) -> None:
    self.app = Flask(__name__)

    class UserParams(BaseModel):
      user_id: str

    class UserRequest(BaseModel):
      data: str

    class UserResponse(BaseModel):
      content: dict

    @self.app.route('/users/<user_id>', methods=['GET'])
    @validation.Validate
    def CreateUser(
        params: UserParams,  # pylint: disable=unused-argument
        request_body: UserRequest  # pylint: disable=unused-argument
    ) -> UserResponse:
      return UserResponse(content={})

    validation_exception.RegisterErrorHandler(self.app)

  def testCombined(self):

    with self.app.test_client() as client:
      response = client.get('/users/foo', json={'data': 'test123'})
      self.assertEqual(response.status_code, 200)
      self.assertEqual(response.get_json(), {'content': {}})
