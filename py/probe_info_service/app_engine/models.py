# Copyright 2022 The ChromiumOS Authors.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

from typing import Optional, Tuple

from google.cloud import datastore

from cros.factory.probe_info_service.app_engine import config
from cros.factory.probe_info_service.app_engine import datastore_utils
from cros.factory.probe_info_service.app_engine import stubby_pb2  # pylint: disable=no-name-in-module


_PB_MODEL_FIELD_CONVERTER_FACTORY = (
    datastore_utils.PBModelFieldConverter
    if config.Config().is_prod else datastore_utils.TextPBModelFieldConverter)


class AVLProbeEntity(datastore_utils.KeyfulModelBase):
  """The model class for probe info / metadata from AVL.

  Attributes:
    cid: The component ID.
    qid: The qualification ID, non-zero when the entity is qualification
      specific.
    probe_info: The recorded probe info.
  """
  cid: int
  qid: int
  # TODO(yhong): Remove this unused field.
  readable_label: str = datastore_utils.ModelField(default='')
  probe_info: stubby_pb2.ProbeInfo = datastore_utils.ModelField(
      converter=_PB_MODEL_FIELD_CONVERTER_FACTORY(stubby_pb2.ProbeInfo),
      default_factory=stubby_pb2.ProbeInfo)

  _ENTITY_CID_GROUP_KIND = 'AVLProbeEntityCIDGroup'
  _ENTITY_KIND = 'AVLProbeEntity'

  def DeriveKeyPathFromModelFields(self):
    """See base class."""
    return self.GetKeyPath(self.cid, self.qid)

  @classmethod
  def GetKeyPath(cls, cid: int, qid: int) -> Tuple[str, ...]:
    return (cls._ENTITY_CID_GROUP_KIND, str(cid), cls._ENTITY_KIND, str(qid))

  @classmethod
  def ConstructQuery(
      cls, client: datastore.Client, cid: Optional[int] = None,
      parent_key: Optional[datastore.Key] = None) -> datastore.Query:
    ancestor_key = (
        client.key(cls._ENTITY_CID_GROUP_KIND, str(cid), parent=parent_key)
        if cid is not None else parent_key)
    return client.query(kind=cls._ENTITY_KIND, ancestor=ancestor_key)
