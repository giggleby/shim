# Copyright 2022 The ChromiumOS Authors.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.
"""Converts legacy probe info entities to `models.AVLProbeEntity`s."""

import logging

from google.cloud import datastore
from google.protobuf import text_format

from cros.factory.probe_info_service.app_engine import config
from cros.factory.probe_info_service.app_engine.migration_scripts import migration_script_types
from cros.factory.probe_info_service.app_engine import stubby_pb2  # pylint: disable=no-name-in-module


class Migrator(migration_script_types.Migrator):
  _FROM_KIND = 'component_probe_info'
  _TO_KIND = 'AVLProbeEntity'
  _TO_PARENT_KIND = 'AVLProbeEntityCIDGroup'

  def Run(self) -> migration_script_types.MigrationResultCase:
    client = datastore.Client()
    try:
      legacy_entities = client.query(kind=self._FROM_KIND).fetch()
    except Exception:
      logging.exception('Unable to fetch %r entities.', self._FROM_KIND)
      return migration_script_types.MigrationResultCase.FAILED_ROLLBACKED

    batch = client.batch()
    batch.begin()
    num_converted_entities = 0
    try:
      for legacy_entity in legacy_entities:
        try:
          comp_id, qual_id = map(int, (legacy_entity.key.name or '').split('-'))
        except ValueError as ex:
          raise ValueError(
              f'Get entity key with incorrect format: {legacy_entity.key!r}.'
          ) from ex
        comp_probe_info = stubby_pb2.ComponentProbeInfo()
        comp_probe_info.ParseFromString(legacy_entity['bytes'])
        if (comp_probe_info.component_identity.component_id != comp_id or
            comp_probe_info.component_identity.qual_id != qual_id):
          raise ValueError('Detect key and properties mismatch from '
                           f'{self._FROM_KIND} entity.')
        entity = client.entity(
            client.key(self._TO_PARENT_KIND, str(comp_id), self._TO_KIND,
                       str(qual_id)))
        entity['cid'] = comp_id
        entity['qid'] = qual_id
        entity['readable_label'] = ''
        if config.Config().is_prod:
          entity['probe_info'] = comp_probe_info.probe_info.SerializeToString()
        else:
          entity['probe_info'] = text_format.MessageToString(
              comp_probe_info.probe_info)
        batch.put(entity)
        batch.delete(legacy_entity.key)
        num_converted_entities += 1
      batch.commit()
    except Exception:
      logging.exception('Failed to perform the migration from %r to %r.',
                        self._FROM_KIND, self._TO_KIND)
      batch.rollback()
      return migration_script_types.MigrationResultCase.FAILED_ROLLBACKED
    logging.info('Migrated %d entries from %s to %s.', num_converted_entities,
                 self._FROM_KIND, self._TO_KIND)
    return migration_script_types.MigrationResultCase.SUCCESS


MIGRATOR = Migrator()
