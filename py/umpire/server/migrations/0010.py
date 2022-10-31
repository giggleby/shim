# Copyright 2018 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

import hashlib
import json
import os

# Private constants.
_ENV_DIR = '/var/db/factory/umpire'
_CONFIG_PATH = os.path.join(_ENV_DIR, 'active_umpire.json')


def SaveNewActiveConfig(config):
  """Serialize and saves the configuration as new active config file."""
  json_config = json.dumps(
      config, indent=2, separators=(',', ': '), sort_keys=True) + '\n'
  json_name =  (
      f"umpire.{hashlib.md5(json_config.encode('utf-8')).hexdigest()}.json"
      )
  json_path = os.path.join('resources', json_name)
  with open(os.path.join(_ENV_DIR, json_path), 'w', encoding='utf8') as f:
    f.write(json_config)

  os.unlink(_CONFIG_PATH)
  os.symlink(json_path, _CONFIG_PATH)


def Migrate():
  with open('/var/db/factory/umpire/active_umpire.json', encoding='utf8') as f:
    config = json.load(f)
  if 'rulesets' in config:
    for r in config['rulesets']:
      r.pop('match', None)
  SaveNewActiveConfig(config)
