# Copyright 2023 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.
"""Update a duplicate resource of bundle.

It reads a factory bundle, copies resources to Umpire repository, and
updates UmpireConfig.

See DuplicateUpdater comments for usage.
"""

import copy
import json

from cros.factory.umpire.server.commands import deploy
from cros.factory.umpire.server import config as umpire_config
from cros.factory.umpire.server import resource


class DuplicateUpdater:
  """Update a duplicate resource of bundle.

  It will update the duplicate bundle resource to Umpire.

  It also try to update active bundle_user_action_state config file and deploy
  it.

  Usage:
    DuplicateUpdater(daemon).Update('old_bundle_id', 'new_bundle_id', 'note',
                                    'resource_type', 'resource_file')
  """
  return_lists = {}

  def __init__(self, daemon):
    """Constructor.

    Args:
      daemon: UmpireDaemon object.
    """
    self._daemon = daemon

  def Update(self, old_bundle_id, new_bundle_id, note, resource_type,
             resource_file):
    """Update a duplicate bundle resource.

    Args:
      old_bundle_id: The ID of the old bundle. If omitted, use bundle_name in
          factory bundle's manifest.
      new_bundle_id: The ID of the new bundle. If omitted, use bundle_name in
          factory bundle's manifest.
      note: A description of this bundle.
      resource_type: type of the resource.
      resource_file: A resource's filename.
    """
    update_payloads = {}
    config = umpire_config.UmpireConfig(self._daemon.env.config)
    bundle = config.GetBundle(old_bundle_id)
    require_user_action = {}
    if 'require_user_action' in bundle:
      require_user_action = copy.deepcopy(bundle['require_user_action'])

    action_index = None
    for index, action in enumerate(require_user_action[resource_type]):
      if action['type'] == 'duplicate':
        action_index = index
        for duplicate in action['file_list']:
          if duplicate['file'] == resource_file:
            update_payloads = {
                resource_type: duplicate
            }
    del require_user_action[resource_type][action_index]
    if bool(require_user_action[resource_type]) is False:
      del require_user_action[resource_type]

    if update_payloads:
      payloads = self._daemon.env.GetPayloadsDict(bundle['payloads'])
      payloads.update(update_payloads)
      payload_json_name = self._daemon.env.AddConfigFromBlob(
          json.dumps(payloads), resource.ConfigTypes.payload_config)
      config['bundles'].insert(
          0, {
              'id': new_bundle_id,
              'note': note,
              'payloads': payload_json_name,
              'require_user_action': require_user_action,
          })
      config['active_bundle_id'] = new_bundle_id
      deploy.ConfigDeployer(self._daemon).Deploy(
          self._daemon.env.AddConfigFromBlob(
              config.Dump(), resource.ConfigTypes.umpire_config))
