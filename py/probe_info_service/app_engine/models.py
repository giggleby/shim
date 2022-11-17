# Copyright 2022 The ChromiumOS Authors
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


class AVLProbeEntry(datastore_utils.KeyfulModelBase):
  """The model class for probe info / metadata from AVL.

  Attributes:
    cid: The component ID.
    qid: The qualification ID, non-zero when the entity is qualification
      specific.
    probe_info: The recorded probe info.
    is_valid: Whether the probe info is valid.
    is_tested: Whether the probe info is verified by runtime probe.
    is_justified_for_overridden: Whether this probe info is justified as not
      useful and probe statement overridden is eligible.
  """
  cid: int
  qid: int
  # TODO(yhong): Remove this unused field.
  readable_label: str = datastore_utils.ModelField(default='')
  probe_info: stubby_pb2.ProbeInfo = datastore_utils.ModelField(
      converter=_PB_MODEL_FIELD_CONVERTER_FACTORY(stubby_pb2.ProbeInfo),
      default_factory=stubby_pb2.ProbeInfo)
  is_valid: bool = datastore_utils.ModelField(default=False)
  is_tested: bool = datastore_utils.ModelField(default=False)
  is_justified_for_overridden: bool = datastore_utils.ModelField(default=False)

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


class AVLProbeEntryManager:
  """Manages the stateful AVL probe entries."""

  def __init__(self):
    self._client = datastore.Client()

  def GetAVLProbeEntry(self, cid: int, qid: int) -> Optional[AVLProbeEntry]:
    """Loads the AVL probe entry by the AVL ID.

    Args:
      cid: The AVL component ID of the target entry.
      qid: The AVL qualification ID of the target entry.

    Returns:
      The corresponding AVL probe entry, or `None` if not found.
    """
    entity = self._client.get(
        self._client.key(*AVLProbeEntry.GetKeyPath(cid, qid)))
    if not entity:
      return None
    return AVLProbeEntry.FromEntity(entity)

  def GetOrCreateAVLProbeEntry(self, cid: int,
                               qid: int) -> Tuple[bool, AVLProbeEntry]:
    """Loads the AVL probe entry by the AVL ID, or creates one if not found.

    Note that if the returned AVL probe entry is a newly created one, caller
    is in charge of manually saving it, e.g. calls `SaveAVLProbeEntry()` later.

    Args:
      cid: The AVL component ID of the target entry.
      qid: The AVL qualification ID of the target entry.

    Returns:
      A 2-tuple with the following:
        1.  A boolean flag indicates whether returned entry is a newly created
            one.
        2.  The corresponding AVL probe entry.
    """
    existing_entry = self.GetAVLProbeEntry(cid, qid)
    if existing_entry is not None:
      return False, existing_entry
    entry = AVLProbeEntry.Create(self._client, cid=cid, qid=qid)
    return True, entry

  def SaveAVLProbeEntry(self, entry: AVLProbeEntry):
    """Saves the given AVL probe entry back to the stateful datastore."""
    self._client.put(entry.entity)

  def CleanupForTest(self):
    if config.Config().is_prod:
      raise RuntimeError(
          'Cleaning up AVLProbeEntry entities is forbidden in production.')
    query = AVLProbeEntry.ConstructQuery(self._client)
    query.keys_only()
    self._client.delete_multi(list(query.fetch()))
