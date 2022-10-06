# Copyright 2022 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

import os
import shutil

_OLD_PARAMETER_DIR = '/var/db/factory/umpire/parameters'
_NEW_FACTORY_DRIVE_DIR = '/var/db/factory/umpire/factory_drives'


def Migrate():
  if os.path.isdir(_OLD_PARAMETER_DIR):
    if not os.path.exists(_NEW_FACTORY_DRIVE_DIR):
      os.mkdir(_NEW_FACTORY_DRIVE_DIR)

    for file_name in os.listdir(_OLD_PARAMETER_DIR):
      if file_name == 'parameters.json':
        os.rename(os.path.join(_OLD_PARAMETER_DIR, file_name),
                  os.path.join(_NEW_FACTORY_DRIVE_DIR, 'factory_drives.json'))
      else:
        os.rename(os.path.join(_OLD_PARAMETER_DIR, file_name),
                  os.path.join(_NEW_FACTORY_DRIVE_DIR, file_name))
    shutil.rmtree(_OLD_PARAMETER_DIR)
