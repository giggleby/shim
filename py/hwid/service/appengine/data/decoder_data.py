# Copyright 2021 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.
"""Holds data models and their management utils regarding decoding HWIDs."""

import logging
from typing import Collection

from google.cloud import ndb

from cros.factory.hwid.service.appengine import ndb_connector as ndbc_module
from cros.factory.hwid.v3 import name_pattern_adapter


class AVLNameMapping(ndb.Model):

  component_id = ndb.IntegerProperty()
  name = ndb.StringProperty()


class PrimaryIdentifier(ndb.Model):
  """Primary identifier for component groups.

  Multiple components could have the same probe values after removing fields
  which are not identifiable like `timing` in dram or `emmc5_fw_ver` in storage.
  This table records those components and chooses one by status (in the order of
  [QUALIFIED, UNQUALIFIED, REJECTED]) then lexicographically smallest name as
  the primary identifier for both GetDutLabels and
  verification_payload_generator to match components by HWID-decoded and probed
  values.
  """
  model = ndb.StringProperty(indexed=True)
  category = ndb.StringProperty(indexed=True)
  comp_name = ndb.StringProperty(indexed=True)
  primary_comp_name = ndb.StringProperty()


class DecoderDataManager:

  def __init__(self, ndb_connector: ndbc_module.NDBConnector):
    self._ndb_connector = ndb_connector

  def SyncAVLNameMapping(self, mapping) -> Collection[int]:
    """Sync the set of AVL name mapping to be exactly the mapping provided.

    Args:
      mapping: The {cid: avl_name} dictionary for updating datastore.

    Returns:
      A collection of CIDs as integers having AVL name mapping
      created, changed, or deleted.
    """

    touched_cids = set()
    with self._ndb_connector.CreateClientContextWithGlobalCache():
      cids_to_create = set(mapping)

      q = AVLNameMapping.query()
      for entry in list(q):
        # Discard the entries indexed by cid.
        if entry.component_id not in mapping:
          entry.key.delete()
          touched_cids.add(entry.component_id)
        else:
          new_name = mapping[entry.component_id]
          if entry.name != new_name:
            touched_cids.add(entry.component_id)
            entry.name = new_name
            entry.put()
          cids_to_create.discard(entry.component_id)

      for cid in cids_to_create:
        touched_cids.add(cid)
        name = mapping[cid]
        entry = AVLNameMapping(component_id=cid, name=name)
        entry.put()
    logging.info('AVL name mapping is synced.')
    return touched_cids

  def GetAVLName(self, category, comp_name, fallback=True):
    """Get AVL Name from hourly updated mapping data.

    Args:
      category: Component category.
      comp_name: Component name defined in HWID DB.
      fallback: whether to fallback to comp_name if fail to query AVL name.

    Returns:
      If the name follows the policy and can be queries from datastore, the AVL
      name is returned.  Otherwise, return comp_name if fallback=True or an
      empty string instead.
    """
    np_adapter = name_pattern_adapter.NamePatternAdapter()
    name_pattern = np_adapter.GetNamePattern(category)
    name_info = name_pattern.Matches(comp_name)
    if not name_info:
      return comp_name if fallback else ''

    with self._ndb_connector.CreateClientContextWithGlobalCache():
      entry = AVLNameMapping.query(
          AVLNameMapping.component_id == name_info.cid).get()
    if entry is None:
      logging.error(
          'mapping not found for category "%s" and component name "%s"',
          category, comp_name)
      return comp_name if fallback else ''
    return entry.name

  def UpdatePrimaryIdentifiers(self, mapping_per_model):
    """Update primary identifiers to datastore.

    This method is for updating the mappings to datastore which will be looked
    up in GetDutLabels API.  To provide consistency, it will clear existing
    mappings per model first.

    Args:
      mapping_per_model: An instance of collections.defaultdict(dict) mapping
          `model` to {(category, component name): target component name}
          mappings.
    """

    with self._ndb_connector.CreateClientContextWithGlobalCache():
      for model, mapping in mapping_per_model.items():
        q = PrimaryIdentifier.query(PrimaryIdentifier.model == model)
        for entry in list(q):
          entry.key.delete()
        for (category, comp_name), primary_comp_name in mapping.items():
          PrimaryIdentifier(model=model, category=category, comp_name=comp_name,
                            primary_comp_name=primary_comp_name).put()

  def GetPrimaryIdentifier(self, model, category, comp_name):
    """Look up existing DUT label mappings from Datastore."""

    with self._ndb_connector.CreateClientContextWithGlobalCache():
      q = PrimaryIdentifier.query(PrimaryIdentifier.model == model,
                                  PrimaryIdentifier.category == category,
                                  PrimaryIdentifier.comp_name == comp_name)
      mapping = q.get()
      return mapping.primary_comp_name if mapping else comp_name

  def CleanAllForTest(self):
    with self._ndb_connector.CreateClientContext():
      for key in AVLNameMapping.query().iter(keys_only=True):
        key.delete()
      for key in PrimaryIdentifier.query().iter(keys_only=True):
        key.delete()
