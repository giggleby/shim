# Copyright 2022 The ChromiumOS Authors.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

import abc
from typing import Any, Callable, Mapping, Optional, Sequence, Tuple, Union

from google.cloud import datastore
from google.protobuf import message as pb_message
from google.protobuf import text_format as pb_text_format

from cros.factory.utils import type_utils


class ModelFieldConverter(abc.ABC):
  """Interface of converters for model field values and entity field values."""

  @abc.abstractmethod
  def ToEntityFieldValue(self, model_field_value: Any) -> Any:
    """Convert the model field value to the corresponding entity field value.

    Args:
      model_field_value: The value to convert.

    Returns:
      The corresponding field value to store in datastore.
    """

  @abc.abstractmethod
  def ToModelFieldValue(self, entity_field_value: Any) -> Any:
    """Convert the entity field value to the corresponding model field value.

    Args:
      entity_field_value: The value to convert.

    Returns:
      The corresponding field value to store in datastore.

    Raises:
      TypeError: If `entity_field_value` is of an unexpected value type.
      ValueError: If the converter fails to convert the data.
    """


class _DefaultModelFieldConverter(ModelFieldConverter):

  def ToEntityFieldValue(self, model_field_value):
    """See base class."""
    return model_field_value

  def ToModelFieldValue(self, entity_field_value):
    """See base class."""
    return entity_field_value


_DEFAULT_NOT_SPECIFIED = object()


class PBModelFieldConverter(ModelFieldConverter):
  """Model field converter for protobuf messages."""

  def __init__(self, pb_cls):
    self._pb_cls = pb_cls

  def ToEntityFieldValue(self, model_field_value):
    """See base class."""
    return model_field_value.SerializeToString()

  def ToModelFieldValue(self, entity_field_value):
    """See base class."""
    if not isinstance(entity_field_value, bytes):
      raise TypeError('Expect bytes for protobuf message field, got '
                      f'{type(entity_field_value)}.')
    try:
      inst = self._pb_cls()
      inst.ParseFromString(entity_field_value)
      return inst
    except pb_message.DecodeError as ex:
      raise ValueError('Unable to load the PB message from the entity.') from ex


class TextPBModelFieldConverter(ModelFieldConverter):
  """Model field converter for protobuf messages using text format."""

  def __init__(self, pb_cls):
    self._pb_cls = pb_cls

  def ToEntityFieldValue(self, model_field_value):
    """See base class."""
    return pb_text_format.MessageToString(model_field_value)

  def ToModelFieldValue(self, entity_field_value):
    """See base class."""
    if not isinstance(entity_field_value, str):
      raise TypeError('Expect string for protobuf message field in text, got '
                      f'{type(entity_field_value)}.')
    try:
      return pb_text_format.Parse(entity_field_value, self._pb_cls())
    except pb_message.DecodeError as ex:
      raise ValueError(
          'Unable to load the PB message in text from the entity.') from ex


class ModelField:
  """Captures the definition of a field in the model class.

  Attributes:
    converter: The converter of this field.
    has_default: Whether the field has a default value or not.
    default_factory: The factory function that takes no arguments and returns
      the default value instance; `None` when `has_default` is `False`.
    exclude_from_index: Whether to exclude this field from index while creating
      the entity.
  """

  def __init__(self, converter: Optional[ModelFieldConverter] = None,
               default: Any = _DEFAULT_NOT_SPECIFIED,
               default_factory: Optional[Callable[[], Any]] = None,
               exclude_from_index: bool = False):
    """Initializer.

    Args:
      converter: The customized converter for this field.
      default: The default value of this field.  It is mutally excluded with
        `default_factory`.
      default_factory: A function that returns the default value for this
        field on invocation without arguments.  It is mutally exclusive with
        `default`.
      exclude_from_index: Whether this field should be excluded from indexing
        while constructing the corresponding datastore entity.
    """
    self.converter = converter or _DefaultModelFieldConverter()
    if default is not _DEFAULT_NOT_SPECIFIED and default_factory:
      raise ValueError('`default` and `default_factory` are mutual.')
    if default is not _DEFAULT_NOT_SPECIFIED:
      self.has_default = True
      self.default_factory = lambda: default
    elif default_factory:
      self.has_default = True
      self.default_factory = default_factory
    else:
      self.has_default = False
      self.default_factory = None
    self.exclude_from_index = exclude_from_index


_DEFAULT_MODEL_FIELD = ModelField()


class _ModelBase(type_utils.Obj):
  """Base class for model definitions.

  Attributes:
    entities: The corresponding datastore entity instance.
  """

  def __init__(
      self,
      entity: Optional[datastore.Entity],
      fields: Mapping[str, Any],
  ):
    """Initializer, which is expected to be called by named constructors.

    Args:
      entity: The corresponding datastore entity instance.  Accept `None` so
        that sub-classes' constructors have the flexibility to assign it later.
      fields: The dictionary that contains the model field values.
    """
    super().__init__(**fields)
    self._entity = entity

  @classmethod
  def _CreateEmptyEntity(cls, client: datastore.Client,
                         key: datastore.Key) -> datastore.Entity:
    """Creates an empty entity for this model class.

    Args:
      client: The datastore client.
      key: The key of the entity.

    Returns:
      An entity instance.
    """
    return client.entity(
        key=key, exclude_from_indexes=[
            field_name for field_name, field_info in cls._GetFields()
            if field_info.exclude_from_index
        ])

  @classmethod
  def FromEntity(cls, entity: datastore.Entity):
    """Loads an instance from the given entity.

    Args:
      entity: The datastore entity to load.

    Returns:
      The loaded model instance.

    Raises:
      ValueError: Failed to load the instance from values provided in the given
        entity.
      TypeError: The given entity is compatible with the model definition.
    """
    model_dict = {}
    missing_field_names = []
    for field_name, field_info in cls._GetFields():
      if field_name in entity:
        model_dict[field_name] = field_info.converter.ToModelFieldValue(
            entity[field_name])
      elif field_info.has_default:
        model_dict[field_name] = field_info.default_factory()
      else:
        missing_field_names.append(field_name)
    if missing_field_names:
      raise TypeError(
          f'Unable to load the entity, missing fields: {missing_field_names}.')
    return cls(entity, model_dict)

  @property
  def entity(self) -> datastore.Entity:
    """See class' docstring."""
    assert self._entity is not None, ('`self._entity` is expected to be '
                                      'configured during instance '
                                      'initialization time.')
    # Write back the field value changes.
    exported_dict = {}
    for field_name, field_info in self._GetFields():
      exported_dict[field_name] = field_info.converter.ToEntityFieldValue(
          getattr(self, field_name))
    for field_name in list(self._entity):
      if field_name not in exported_dict:
        self._entity.pop(field_name)
    self._entity.update(exported_dict)
    return self._entity

  @classmethod
  def _GetFields(cls) -> Sequence[Tuple[str, ModelField]]:
    return [(field_name, getattr(cls, field_name, _DEFAULT_MODEL_FIELD))
            for field_name in cls.__annotations__]

  @classmethod
  def _ParseFieldInitValues(
      cls,
      fields: Mapping[str, Any],
  ) -> Mapping[str, Any]:
    fields = dict(fields)  # Clone the instance to make it modifiable.
    model_dict = {}
    missing_field_names = []
    for field_name, field_info in cls._GetFields():
      if field_name in fields:
        model_dict[field_name] = fields.pop(field_name)
      elif field_info.has_default:
        model_dict[field_name] = field_info.default_factory()
      else:
        missing_field_names.append(field_name)
    if missing_field_names:
      raise TypeError(f'Unable to create a new {cls}, '
                      f'missing fields: {missing_field_names}.')
    if fields:
      raise TypeError(f'Unable to create a new {cls}, '
                      f'got extra fields: {list(fields)}.')

    return model_dict


class KeylessModelBase(_ModelBase):
  """Base class for models which key is unrelated to the field values."""

  @classmethod
  def Create(cls, client: datastore.Client, key: datastore.Key, **fields):
    """Creates a new model instance.

    Args:
      client: The datastore client as a factory for entity creation.
      key: The entity key.
      fields: Field values of the model.

    Returns:
      The created model instance.

    Raises:
      TypeError: If some field values are missing.
    """
    return cls(
        cls._CreateEmptyEntity(client, key), cls._ParseFieldInitValues(fields))


class KeyMismatchError(Exception):
  """Raises if the key derived from the model data mismatches the entity's."""


class KeyfulModelBase(_ModelBase):
  """Base class for models which key is determined by the field values."""

  def DeriveKeyPathFromModelFields(self) -> Tuple[Union[str, int]]:
    """Returns the path list of key of this model.

    This method must not access `self.entity` or `self._entity` as it should
    derive the key path purely from the data stored in the model.

    Returns:
      A list of key path args.  If the length is even, the list contains
      `[<kind>, <identity>, <sub-kind>, <identity>, ...]`;  otherwise,
      the list doesn't contain the root kind.
    """
    raise NotImplementedError

  def _ValidateDerivedKeyMatchesEntityKey(self):
    # Expect entity key to be complete at this stage.
    model_key_path = self.DeriveKeyPathFromModelFields()
    entity_key_path = self._entity.key.flat_path
    if len(entity_key_path) < len(model_key_path):
      raise KeyMismatchError('Entity key path is too short.')
    if any(entity_key_path[i] != model_key_path[i]
           for i in range(-1, -len(model_key_path) - 1, -1)):
      raise KeyMismatchError('Entity key and model key mismatch.')

  @classmethod
  def FromEntity(cls, entity: datastore.Entity) -> 'cls':
    """See base class."""
    if entity.key.is_partial:
      raise ValueError('Entity key is not complete.')
    instance = super().FromEntity(entity)
    instance._ValidateDerivedKeyMatchesEntityKey()  # pylint: disable=protected-access
    return instance

  @classmethod
  def Create(cls, client: datastore.Client,
             parent_key: Optional[datastore.Key] = None, **fields):
    """Creates a new model instance.

    Args:
      client: The datastore client as a factory for entity creation.
      parent_key: A complete datastore key as the parent key.
      fields: Field values of the model.

    Returns:
      The created model instance.

    Raises:
      ValueError: If the parent key is invalid.
      TypeError: If some field values are missing.
    """
    instance = cls(None, cls._ParseFieldInitValues(fields))
    model_key_path = instance.DeriveKeyPathFromModelFields()
    is_parent_key_partial = parent_key.is_partial if parent_key else False
    if len(model_key_path) % 2 != (1 if is_parent_key_partial else 0):
      raise ValueError('Parent key is incompatible with derived model key.')
    if is_parent_key_partial:
      parent_key = parent_key.completed_key(model_key_path[0])
      model_key_path = model_key_path[1:]
    key = client.key(*model_key_path,
                     parent_key=parent_key) if model_key_path else parent_key
    instance._entity = cls._CreateEmptyEntity(client, key)
    return instance

  @property
  def entity(self) -> datastore.Entity:
    """See base class."""
    self._ValidateDerivedKeyMatchesEntityKey()
    return super().entity
