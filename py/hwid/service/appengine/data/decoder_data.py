# Copyright 2021 The Chromium OS Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.
"""Holds data models and their management utils regarding decoding HWIDs."""

import logging

from google.cloud import ndb  # pylint: disable=no-name-in-module, import-error

from cros.factory.hwid.service.appengine import ndb_connector as ndbc_module
from cros.factory.hwid.v3 import name_pattern_adapter


class AVLNameMapping(ndb.Model):

  category = ndb.StringProperty()
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

  def __init__(self, ndb_connector: ndbc_module):
    self._ndb_connector = ndb_connector

  def SyncAVLNameMapping(self, category, mapping):
    """Sync the set of AVL name mapping to be exactly the mapping provided.

    Args:
      category: The component category
      mapping: The {cid: avl_name} dictionary for updating datastore.
    """

    with self._ndb_connector.CreateClientContextWithGlobalCache():
      cids_to_create = set(mapping)

      q = AVLNameMapping.query(AVLNameMapping.category == category)
      for entry in list(q):
        # Discard the entries indexed by cid.
        if entry.component_id not in mapping:
          entry.key.delete()
        else:
          entry.name = mapping[entry.component_id]
          entry.put()
          cids_to_create.discard(entry.component_id)

      for cid in cids_to_create:
        name = mapping[cid]
        entry = AVLNameMapping(component_id=cid, name=name, category=category)
        entry.put()
    logging.info('AVL name mapping of category "%s" is synced.', category)

  def ListExistingAVLCategories(self):
    with self._ndb_connector.CreateClientContextWithGlobalCache():
      category_set = set()
      for entry in AVLNameMapping.query(projection=['category'],
                                        distinct_on=['category']):
        category_set.add(entry.category)
      logging.debug('category_set: %s', category_set)
      return category_set

  def RemoveAVLNameMappingCategories(self, category_set):
    with self._ndb_connector.CreateClientContextWithGlobalCache():
      keys_to_delete = []
      for category in category_set:
        logging.info('Add category "%s" to remove', category)
        keys_to_delete += AVLNameMapping.query(
            AVLNameMapping.category == category).fetch(keys_only=True)
      logging.debug('keys_to_delete: %s', keys_to_delete)
      ndb.delete_multi(keys_to_delete)
      logging.info('Extra categories are Removed')

  def GetAVLName(self, category, comp_name):
    """Get AVL Name from hourly updated mapping data.

    Args:
      category: Component category.
      comp_name: Component name defined in HWID DB.

    Returns:
      comp_name if the name does not follow the <category>_<cid>_<qid>#<comment>
      rule, or the mapped name defined in datastore.
    """
    np_adapter = name_pattern_adapter.NamePatternAdapter()
    name_pattern = np_adapter.GetNamePattern(category)
    ret = name_pattern.Matches(comp_name)
    if ret is None:
      return comp_name
    cid, unused_qid = ret

    with self._ndb_connector.CreateClientContextWithGlobalCache():
      entry = AVLNameMapping.query(AVLNameMapping.category == category,
                                   AVLNameMapping.component_id == cid).get()
    if entry is None:
      logging.error(
          'mapping not found for category "%s" and component name "%s"',
          category, comp_name)
      return comp_name
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
