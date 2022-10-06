#!/usr/bin/env python3
# Copyright 2020 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

import os
import sys
import unittest

from cros.factory.test.env import paths


class DummyCliUnittest(unittest.TestCase):
  def testImportCrosFactory(self):
    from cros.factory.cli import factory_env  # pylint: disable=unused-import

  def testSysPath(self):
    self.assertIn(os.path.join(paths.FACTORY_DIR, 'py_pkg'), ' '.join(sys.path))


if __name__ == '__main__':
  unittest.main()
