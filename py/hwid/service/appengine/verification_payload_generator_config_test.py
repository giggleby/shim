# Copyright 2022 The Chromium OS Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

import unittest

from cros.factory.hwid.service.appengine import verification_payload_generator_config as vpg_config_module


class VerificationPayloadGeneratorConfigTest(unittest.TestCase):

  def testDefaultValue(self):
    vpg_config = vpg_config_module.VerificationPayloadGeneratorConfig.Create()
    self.assertEqual(vpg_config.board, "")
    self.assertEqual(vpg_config.ignore_error, [])
    self.assertEqual(vpg_config.waived_comp_categories, [])

  def testWithConfig(self):
    config = {
        'board': 'foo',
        'waived_comp_categories': ['battery'],
        'ignore_error': ['stylus'],
    }
    vpg_config = vpg_config_module.VerificationPayloadGeneratorConfig.Create(
        **config)
    self.assertEqual(vpg_config.board, 'foo')
    self.assertEqual(vpg_config.ignore_error, ['stylus'])
    self.assertEqual(vpg_config.waived_comp_categories, ['battery'])


if __name__ == '__main__':
  unittest.main()
