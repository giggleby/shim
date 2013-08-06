#!/usr/bin/python
#
# Copyright (c) 2012 The Chromium OS Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.


import logging
import unittest

import factory_common  # pylint: disable=W0611
from cros.factory.utils.string_utils import ParseDict, DictToLines


_LINES = ['TPM Enabled: true',
          'TPM Owned: false',
          'TPM Being Owned: false',
          'TPM Ready: false',
          'TPM Password:']
_DICT_RESULT = {'TPM Being Owned': 'false',
                'TPM Ready': 'false',
                'TPM Password': '',
                'TPM Enabled': 'true',
                'TPM Owned': 'false'}
_DICT_TO_LINES_RESULT = ['TPM Being Owned:false',
                         'TPM Enabled:true',
                         'TPM Owned:false',
                         'TPM Password:',
                         'TPM Ready:false']


class ParseDictTest(unittest.TestCase):
  def testParseDict(self):
    self.assertEquals(_DICT_RESULT, ParseDict(_LINES, ':'))

class DictToLinesTest(unittest.TestCase):
  def testDictToLines(self):
    dict_result = ParseDict(_LINES, ':')
    lines = DictToLines(dict_result, ':')
    self.assertEquals(_DICT_TO_LINES_RESULT, lines)

if __name__ == '__main__':
  logging.basicConfig(level=logging.INFO)
  unittest.main()
