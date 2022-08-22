# Copyright 2022 The ChromiumOS Authors.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.
"""Appends some fields in `models.AVLProbeEntry`."""

import itertools
import logging

from google.cloud import datastore

from cros.factory.probe_info_service.app_engine.migration_scripts import migration_script_types


class Migrator(migration_script_types.Migrator):
  _KIND = 'AVLProbeEntity'
  _MAX_NUM_ENTITIES_PER_BATCH = 200

  def Run(self) -> migration_script_types.MigrationResultCase:
    client = datastore.Client()
    try:
      query = client.query(kind=self._KIND)
      entities_iter = query.fetch()
    except Exception:
      logging.exception('Unable to fetch %r entities.', self._KIND)
      return migration_script_types.MigrationResultCase.FAILED_ROLLBACKED

    num_handled_entities = 0
    might_have_remaining_entities = True
    try:
      while might_have_remaining_entities:
        with client.batch() as batch:
          might_have_remaining_entities = False
          for entity in itertools.islice(entities_iter,
                                         self._MAX_NUM_ENTITIES_PER_BATCH):
            might_have_remaining_entities = True
            entity.update({
                'is_valid': True,
                'is_tested': False,
                'is_justified_for_overridden': False,
            })
            batch.put(entity)
            num_handled_entities += 1
    except Exception:
      logging.exception('Failed to perform the migration to add fields to %r.',
                        self._KIND)
      return migration_script_types.MigrationResultCase.FAILED_ROLLBACKED
    logging.info('Added newly introduced fields to %d %s entries.',
                 num_handled_entities, self._KIND)
    return migration_script_types.MigrationResultCase.SUCCESS


MIGRATOR = Migrator()
