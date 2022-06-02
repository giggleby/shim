#!/usr/bin/env python3
# Copyright 2017 The Chromium OS Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.


import os
import unittest

import jsonschema

from cros.factory.utils import json_utils


class GoofyGhostSchemaTest(unittest.TestCase):

  def loadJSON(self, name):
    parent_dir = os.path.dirname(os.path.abspath(__file__))
    return json_utils.LoadFile(os.path.join(parent_dir, name))

  def runTest(self):
    schema = self.loadJSON('goofy_ghost.schema.json')
    jsonschema.validate(self.loadJSON('goofy_ghost.json'), schema)
    jsonschema.validate(self.loadJSON('goofy_ghost.sample.json'), schema)


if __name__ == '__main__':
  unittest.main()
