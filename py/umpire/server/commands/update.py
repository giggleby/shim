# Copyright 2017 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Updates a resource in a bundle.

See ResourceUpdater for detail.
"""

import copy
import json
import os
import time

from cros.factory.umpire import common
from cros.factory.umpire.server.commands import deploy
from cros.factory.umpire.server import config as umpire_config
from cros.factory.umpire.server import resource
from cros.factory.utils import process_utils


class ResourceUpdater:
  """Updates a resource in a bundle from active config.

  It copies the given resources to Umpire repository. Then updates the
  specified bundle's resource mapping. Finally, it adds the updated config
  to resources and deploys it.

  Usage:
    resource_updater = ResourceUpdater(daemon)
    resource_updater.Update(resources_to_update, source_id='old_bundle_id',
                            dest_id='new_bundle_id')
  """

  def __init__(self, daemon):
    """Constructor.

    Args:
      daemon: UmpireDaemon object.
    """
    self._daemon = daemon

  def _CheckPayloadsList(self, payloads_to_update):
    """Check the correctness of payloads list."""
    for type_name, file_path in payloads_to_update:
      if type_name not in resource.PayloadTypeNames:
        raise common.UmpireError(f'Unsupported payload type: {type_name}')
      if not os.path.isfile(file_path):
        raise common.UmpireError(f'File not found: {file_path}')

  def _CheckPayloadsConfig(self, payloads_config_to_update):
    """Check the correctness of payloads config."""
    for type_name in payloads_config_to_update:
      if type_name not in resource.PayloadTypeNames:
        raise common.UmpireError(f'Unsupported payload type: {type_name}')

  def _MakePayloads(self, payloads_to_update):
    new_payloads = {}
    for type_name, path in payloads_to_update:
      new_payloads.update(self._daemon.env.AddPayload(path, type_name))
    return new_payloads

  def _UpdatePayloads(self, bundle, payloads_to_update):
    payloads = self._daemon.env.GetPayloadsDict(bundle['payloads'])
    payloads.update(payloads_to_update)
    bundle['payloads'] = self._daemon.env.AddConfigFromBlob(
        json.dumps(payloads), resource.ConfigTypeNames.payload_config)

  def _Deploy(self, config):
    deploy.ConfigDeployer(self._daemon).Deploy(
        self._daemon.env.AddConfigFromBlob(
            config.Dump(), resource.ConfigTypeNames.umpire_config))

  def Update(self, payloads_to_update, source_id=None, dest_id=None):
    """Updates payload(s) in a bundle.

    Args:
      payloads_to_update: list of (type_name, file_path) to update.
      source_id: source bundle's ID. If omitted, uses default bundle.
      dest_id: If specified, it copies source bundle with ID dest_id and
          replaces the specified resource(s). Otherwise, it replaces
          resource(s) in place.
    """
    self._CheckPayloadsList(payloads_to_update)

    messages = []
    for type_name, file_path in payloads_to_update:
      if type_name == 'netboot_firmware':
        temp_output = process_utils.CheckOutput([
            '/usr/local/factory/bin/image_tool', 'netboot', '-i', file_path,
            '-m'
        ])
        netboot_firmware_information = json.loads(temp_output)
        # Check if argsfile and bootfile file are exist.
        for key in ('argsfile', 'bootfile'):
          netboot_firmware_file = netboot_firmware_information[key]
          if not os.path.isfile('/mnt/tftp/%s' % netboot_firmware_file):
            messages.append('%s is missing' % netboot_firmware_file)
        # Check if tftp_server_ip is same as the ip set.
        host_ip = process_utils.CheckOutput(['ip', 'route']).split()[2]
        tftp_server_ip = netboot_firmware_information['tftp_server_ip']
        if tftp_server_ip and tftp_server_ip != host_ip:
          messages.append('The tftp_server_ip "%s" does not equal to "%s". ' %
                          (tftp_server_ip, host_ip))

    config = umpire_config.UmpireConfig(self._daemon.env.config)
    if not source_id:
      source_id = config.GetActiveBundle()['id']
    bundle = config.GetBundle(source_id)
    if not bundle:
      raise common.UmpireError(f'Source bundle ID does not exist: {source_id}')
    if dest_id:
      if config.GetBundle(dest_id):
        raise common.UmpireError(
            f'Destination bundle ID already exists: {dest_id}')
      bundle = copy.deepcopy(bundle)
      bundle['id'] = dest_id
      config['bundles'].append(bundle)

    payloads_to_update = self._MakePayloads(payloads_to_update)
    self._UpdatePayloads(bundle, payloads_to_update)
    self._Deploy(config)
    return json.dumps(messages)

  def UpdateFromConfig(self, payloads_config_to_update, update_note=''):
    """Updates payload(s) in a new bundle with payloads config.

    Args:
      payloads_config_to_update: The payload config dictionary to update.
      update_note: A description for the updated bundle.
    """
    self._CheckPayloadsConfig(payloads_config_to_update)

    config = umpire_config.UmpireConfig(self._daemon.env.config)
    dest_id = time.strftime('factory_bundle_%Y%m%d_%H%M%S')
    while config.GetBundle(dest_id):
      dest_id = time.strftime('factory_bundle_%Y%m%d_%H%M%S')

    old_bundle = config.GetBundle(config.GetActiveBundle()['id'])
    bundle = copy.deepcopy(old_bundle)
    bundle['id'] = dest_id
    bundle['note'] = update_note

    config['bundles'].insert(0, bundle)
    config['active_bundle_id'] = dest_id

    self._UpdatePayloads(bundle, payloads_config_to_update)
    self._Deploy(config)
