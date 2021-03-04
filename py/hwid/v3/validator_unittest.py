#!/usr/bin/env python3
# Copyright 2019 The Chromium OS Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.


import os.path
import unittest

from cros.factory.hwid.v3 import filesystem_adapter
from cros.factory.hwid.v3 import validator
from cros.factory.hwid.v3 import validator_context
from cros.factory.hwid.v3.database import Database


_TEST_DATA_PATH = os.path.join(os.path.dirname(__file__), 'testdata')

DB_DRAM_GOOD_PATH = os.path.join(_TEST_DATA_PATH,
                                 'test_database_db_good_dram.yaml')
DB_DRAM_BAD_PATH = os.path.join(_TEST_DATA_PATH,
                                'test_database_db_bad_dram.yaml')
DB_COMP_BEFORE_PATH = os.path.join(
    _TEST_DATA_PATH, 'test_database_db_comp_before.yaml')
DB_COMP_AFTER_GOOD_PATH = os.path.join(
    _TEST_DATA_PATH, 'test_database_db_comp_good_change.yaml')
DB_COMP_AFTER_BAD_PATH = os.path.join(
    _TEST_DATA_PATH, 'test_database_db_comp_bad_change.yaml')


class ValidatorTest(unittest.TestCase):
  def testGoodDramField(self):
    db = Database.LoadFile(DB_DRAM_GOOD_PATH, verify_checksum=False)
    # pylint: disable=protected-access
    validator._ValidateDram(db)

  def testBadDramField(self):
    db = Database.LoadFile(DB_DRAM_BAD_PATH, verify_checksum=False)
    with self.assertRaises(validator.ValidationError) as error:
      # pylint: disable=protected-access
      validator._ValidateDram(db)
    self.assertEqual(
        str(error.exception), ("'dram_type_256mb_and_real_is_512mb' does not "
                               "contain size property"))

  def testGoodCompNameChange(self):
    prev_db = Database.LoadFile(DB_COMP_BEFORE_PATH)
    db = Database.LoadFile(DB_COMP_AFTER_GOOD_PATH)
    ctx = validator_context.ValidatorContext(
        filesystem_adapter=filesystem_adapter.LocalFileSystemAdapter(
            _TEST_DATA_PATH))
    validator.ValidateChange(prev_db, db, ctx)

  def testBadCompNameChange(self):
    prev_db = Database.LoadFile(DB_COMP_BEFORE_PATH)
    db = Database.LoadFile(DB_COMP_AFTER_BAD_PATH)
    ctx = validator_context.ValidatorContext(
        filesystem_adapter=filesystem_adapter.LocalFileSystemAdapter(
            _TEST_DATA_PATH))
    with self.assertRaises(validator.ValidationError) as error:
      validator.ValidateChange(prev_db, db, ctx)
    self.assertEqual(
        str(error.exception),
        "'cpu_z' does not match any available test_component pattern")


if __name__ == '__main__':
  unittest.main()
