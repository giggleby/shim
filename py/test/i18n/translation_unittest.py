#!/usr/bin/python
# Copyright 2017 The Chromium OS Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.


import unittest

import factory_common  # pylint: disable=unused-import
from cros.factory.test.i18n import unittest_test_case
from cros.factory.test.i18n import translation


class TranslationTest(unittest_test_case.I18nTestCase):

  def testGetTranslation(self):
    self.assertEqual('text-1',
                     translation.GetTranslation('text 1', 'zh-CN'))
    self.assertEqual('text 1',
                     translation.GetTranslation('text 1', 'en-US'))
    self.assertEqual('untranslated',
                     translation.GetTranslation('untranslated', 'zh-CN'))
    self.assertEqual('', translation.GetTranslation('', 'zh-CN'))

  def testUnderscore(self):
    self.assertEqual({'en-US': 'text 1', 'zh-CN': 'text-1'},
                     translation._('text 1'))
    self.assertEqual({'en-US': 'untranslated', 'zh-CN': 'untranslated'},
                     translation._('untranslated'))

  def testNoTranslation(self):
    self.assertEqual({'en-US': 'text 1', 'zh-CN': 'text 1'},
                     translation.NoTranslation('text 1'))
    self.assertEqual({'en-US': 'untranslated', 'zh-CN': 'untranslated'},
                     translation.NoTranslation('untranslated'))
    self.assertEqual({'en-US': 0xdeadbeef, 'zh-CN': 0xdeadbeef},
                     translation.NoTranslation(0xdeadbeef))

  def testTranslatedTranslate(self):
    self.assertEqual({'en-US': 'text 1', 'zh-CN': 'text-1'},
                     translation.Translated('text 1'))
    self.assertEqual({'en-US': 'text 1', 'zh-CN': 'text 2'},
                     translation.Translated(
                         {'en-US': 'text 1', 'zh-CN': 'text 2'}))
    self.assertEqual({'en-US': 'text 1', 'zh-CN': 'text 1'},
                     translation.Translated({'en-US': 'text 1'}))

  def testTranslatedNoTranslate(self):
    self.assertEqual({'en-US': 'text 1', 'zh-CN': 'text 1'},
                     translation.Translated('text 1', translate=False))
    self.assertEqual({'en-US': 'text 1', 'zh-CN': 'text 2'},
                     translation.Translated(
                         {'en-US': 'text 1', 'zh-CN': 'text 2'},
                         translate=False))
    self.assertEqual({'en-US': 'text 1', 'zh-CN': 'text 1'},
                     translation.Translated(
                         {'en-US': 'text 1'}, translate=False))

  def testTranslatedNoDefaultLocale(self):
    self.assertRaisesRegexp(
        ValueError, "doesn't contains default locale",
        translation.Translated, {'zh-CN': 'zh'})
    self.assertRaisesRegexp(
        ValueError, "doesn't contains default locale",
        translation.Translated, {'zh-CN': 'zh'}, translate=False)

  def testTranslatedBackwardCompatibleTuple(self):
    self.assertEqual({'en-US': 'en', 'zh-CN': 'zh'},
                     translation.Translated(('en', 'zh')))

if __name__ == '__main__':
  unittest.main()
