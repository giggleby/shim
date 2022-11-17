# Copyright 2022 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

import unittest

from google.cloud import datastore

from cros.factory.probe_info_service.app_engine import datastore_utils
from cros.factory.probe_info_service.app_engine import stubby_pb2  # pylint: disable=no-name-in-module


ENTITY_KIND = 'unused_kind'


class _DatastoreTestBase(unittest.TestCase):

  def setUp(self):
    super().setUp()
    self.client = datastore.Client()
    self.used_entity_kinds = [ENTITY_KIND]

  def tearDown(self):
    for kind in self.used_entity_kinds:
      q = self.client.query(kind=kind)
      q.keys_only()
      self.client.delete_multi([e.key for e in q.fetch()])


class KeylessModelBaseTest(_DatastoreTestBase):

  def testCreateWithMissingFieldValuesThenRaise(self):

    class TestModel(datastore_utils.KeylessModelBase):
      field1: int

    with self.assertRaises(TypeError):
      unused_model = TestModel.Create(self.client, self.client.key(ENTITY_KIND))

  def testCreateWithExtraFieldValuesThenRaise(self):

    class TestModel(datastore_utils.KeylessModelBase):
      field1: int

    with self.assertRaises(TypeError):
      unused_model = TestModel.Create(self.client, self.client.key(ENTITY_KIND),
                                      field1=3, field2=4)

  def testCreateWithFieldValuesThenSuccess(self):

    class TestModel(datastore_utils.KeylessModelBase):
      field1: int
      field2: int = datastore_utils.ModelField(default=2)
      field3: int = datastore_utils.ModelField(default_factory=lambda: 3)

    model = TestModel.Create(self.client, self.client.key(ENTITY_KIND),
                             field1=1)

    self.assertEqual(model.field1, 1)
    self.assertEqual(model.field2, 2)
    self.assertEqual(model.field3, 3)

  def testLoadFromEntityWithMissingFieldThenRaise(self):
    entity = self.client.entity(self.client.key(ENTITY_KIND))

    class TestModel(datastore_utils.KeylessModelBase):
      field1: int

    with self.assertRaises(TypeError):
      unused_model = TestModel.FromEntity(entity)

  def testLoadFromEntityWithExtraFieldThenSuccess(self):
    entity = self.client.entity(self.client.key(ENTITY_KIND))
    entity['field1'] = 3
    entity['extra_field'] = 100

    class TestModel(datastore_utils.KeylessModelBase):
      field1: int

    model = TestModel.FromEntity(entity)

    self.assertEqual(model.field1, 3)

  def testLoadFromEntitySuccess(self):
    entity = self.client.entity(self.client.key(ENTITY_KIND))
    entity.update({'field1': 1})

    class TestModel(datastore_utils.KeylessModelBase):
      field1: int
      field2: int = datastore_utils.ModelField(default=2)
      field3: int = datastore_utils.ModelField(default_factory=lambda: 3)

    model = TestModel.FromEntity(entity)

    self.assertEqual(model.field1, 1)
    self.assertEqual(model.field2, 2)
    self.assertEqual(model.field3, 3)

  def testCorrespondingEntityReflectChanges(self):

    class TestModel(datastore_utils.KeylessModelBase):
      field1: int

    model = TestModel.Create(self.client, self.client.key(ENTITY_KIND),
                             field1=123)

    self.assertEqual(model.entity['field1'], 123)

    model.field1 = 456

    self.assertEqual(model.entity['field1'], 456)


class KeyfulModelBaseTest(_DatastoreTestBase):

  class TestModelWithField1AsID(datastore_utils.KeyfulModelBase):
    field1: int

    def DeriveKeyPathFromModelFields(self):
      return (self.field1, )

  def testCreateWithMissingFieldValuesThenRaise(self):

    with self.assertRaises(TypeError):
      unused_model = self.TestModelWithField1AsID.Create(
          self.client, parent_key=self.client.key(ENTITY_KIND))

  def testCreateWithExtraFieldValuesThenRaise(self):

    with self.assertRaises(TypeError):
      unused_model = self.TestModelWithField1AsID.Create(
          self.client, parent_key=self.client.key(ENTITY_KIND), field1=3,
          field2=4)

  def testCreateWithIncompatibleKey(self):

    with self.assertRaises(ValueError):
      unused_model = self.TestModelWithField1AsID.Create(
          self.client, field1=123)

  def testCreateWithFieldValuesThenSuccess(self):

    class TestModel(datastore_utils.KeyfulModelBase):
      field1: int
      field2: int = datastore_utils.ModelField(default=2)
      field3: int = datastore_utils.ModelField(default_factory=lambda: 3)

      def DeriveKeyPathFromModelFields(self):
        return (self.field1, )

    model = TestModel.Create(self.client,
                             parent_key=self.client.key(ENTITY_KIND), field1=1)

    self.assertEqual(model.field1, 1)
    self.assertEqual(model.field2, 2)
    self.assertEqual(model.field3, 3)

  def testCreatedModelContainsModelDerivedID(self):
    self.used_entity_kinds.append('the_kind')

    model = self.TestModelWithField1AsID.Create(
        self.client, parent_key=self.client.key('the_kind'), field1=1)

    self.assertSequenceEqual(model.entity.key.flat_path, ('the_kind', 1))

  def testCreatedModelContainsModelDerivedFullKey(self):
    self.used_entity_kinds.append('TheKind')

    class TestModel(datastore_utils.KeyfulModelBase):
      field1: int

      def DeriveKeyPathFromModelFields(self):
        return ('TheKind', self.field1)

    model = TestModel.Create(self.client, field1=1)

    self.assertSequenceEqual(model.entity.key.flat_path, ('TheKind', 1))

  def testLoadFromEntityWithMissingFieldThenRaise(self):
    entity = self.client.entity(self.client.key(ENTITY_KIND, 1))

    with self.assertRaises(TypeError):
      unused_model = self.TestModelWithField1AsID.FromEntity(entity)

  def testLoadFromEntityWithIncorrectFieldThenRaise(self):
    entity = self.client.entity(self.client.key(ENTITY_KIND, 123))
    entity['field1'] = 1

    with self.assertRaises(datastore_utils.KeyMismatchError):
      unused_model = self.TestModelWithField1AsID.FromEntity(entity)

  def testLoadFromEntitySuccess(self):
    entity_id = 1
    entity = self.client.entity(self.client.key(ENTITY_KIND, entity_id))
    entity.update({
        'field1': entity_id,
        'extra_field': 123,
    })

    class TestModel(datastore_utils.KeylessModelBase):
      field1: int
      field2: int = datastore_utils.ModelField(default=2)
      field3: int = datastore_utils.ModelField(default_factory=lambda: 3)

      def DeriveKeyPathFromModelFields(self):
        return (self.field1, )

    model = TestModel.FromEntity(entity)

    self.assertEqual(model.field1, 1)
    self.assertEqual(model.field2, 2)
    self.assertEqual(model.field3, 3)

  def testCorrespondingEntityReflectChanges(self):

    class TestModel(datastore_utils.KeylessModelBase):
      field1: int
      field2: int

      def DeriveKeyPathFromModelFields(self):
        return (self.field1, )

    model = TestModel.Create(self.client, self.client.key(ENTITY_KIND),
                             field1=1, field2=2)

    self.assertEqual(model.entity['field2'], 2)

    model.field2 = 200

    self.assertEqual(model.entity['field2'], 200)

  def testModelKeyChangeThanRaiseWhenRetrieveEntity(self):
    model = self.TestModelWithField1AsID.Create(self.client,
                                                self.client.key(ENTITY_KIND),
                                                field1=1)

    model.field1 = 123

    with self.assertRaises(datastore_utils.KeyMismatchError):
      unused_entity = model.entity


class PBModelFieldConverterTest(_DatastoreTestBase):

  def testCanConvertToEntityAndLoadBack(self):

    class TestModel(datastore_utils.KeylessModelBase):
      field1: stubby_pb2.ComponentIdentity = datastore_utils.ModelField(
          converter=datastore_utils.PBModelFieldConverter(
              stubby_pb2.ComponentIdentity))

    the_component_identity = stubby_pb2.ComponentIdentity(component_id=123)
    model = TestModel.Create(self.client, self.client.key(ENTITY_KIND),
                             field1=the_component_identity)
    loaded_model = TestModel.FromEntity(model.entity)

    self.assertEqual(loaded_model.field1, the_component_identity)


class TextPBModelFieldConverterTest(_DatastoreTestBase):

  def testCanConvertToEntityAndLoadBack(self):

    class TestModel(datastore_utils.KeylessModelBase):
      field1: stubby_pb2.ComponentIdentity = datastore_utils.ModelField(
          converter=datastore_utils.TextPBModelFieldConverter(
              stubby_pb2.ComponentIdentity))

    the_component_identity = stubby_pb2.ComponentIdentity(component_id=123)
    model = TestModel.Create(self.client, self.client.key(ENTITY_KIND),
                             field1=the_component_identity)
    loaded_model = TestModel.FromEntity(model.entity)

    self.assertEqual(loaded_model.field1, the_component_identity)


if __name__ == '__main__':
  unittest.main()
