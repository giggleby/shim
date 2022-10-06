# Copyright 2017 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Methods to manipulate ghost properties file."""

import os

from cros.factory.test.env import paths
from cros.factory.utils import json_utils
from cros.factory.utils import process_utils

DEVICE_GOOFY_GHOST_PROPERTIES_FILE = os.path.join(paths.DATA_DIR, 'config',
                                                  'goofy_ghost.json')
GOOFY_GHOST_PROPERTIES_FILE = os.path.join(paths.RUNTIME_VARIABLE_DATA_DIR,
                                           'factory', 'goofy_ghost.json')
GOOFY_GHOST_BIN = os.path.join(paths.FACTORY_DIR, 'bin', 'goofy_ghost')


def ReadProperties():
  return json_utils.LoadFile(GOOFY_GHOST_PROPERTIES_FILE)


def UpdateDeviceProperties(update):
  properties = {}
  if os.path.exists(DEVICE_GOOFY_GHOST_PROPERTIES_FILE):
    properties = json_utils.LoadFile(DEVICE_GOOFY_GHOST_PROPERTIES_FILE)
  properties.update(update)
  json_utils.DumpFile(DEVICE_GOOFY_GHOST_PROPERTIES_FILE, properties, indent=2)
  process_utils.Spawn([GOOFY_GHOST_BIN, 'reset'], check_call=True, log=True)
