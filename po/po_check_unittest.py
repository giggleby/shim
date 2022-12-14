#!/usr/bin/env python3
# Copyright 2017 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.


import collections
import glob
import logging
import os
import re
import shutil
import string
import tempfile
import unittest

from cros.factory.test.i18n import translation
from cros.factory.utils import file_utils
from cros.factory.utils import process_utils


SCRIPT_DIR = os.path.dirname(__file__)


class _MockValue:
  """A mock value that accepts all format_spec for __format__."""
  def __format__(self, format_spec):
    del format_spec  # Unused.
    return ''


class PoBuildTest(unittest.TestCase):
  """Basic sanity check for po files."""

  @classmethod
  def setUpClass(cls):
    cls.temp_dir = tempfile.mkdtemp(prefix='po_check_test.')
    cls.po_dir = os.path.join(cls.temp_dir, 'po')
    cls.build_dir = os.path.join(cls.temp_dir, 'build')
    cls.locale_dir = os.path.join(cls.build_dir, 'locale')

    po_files = glob.glob(os.path.join(SCRIPT_DIR, '*.po'))
    os.makedirs(cls.po_dir)
    for po_file in po_files:
      shutil.copy(po_file, cls.po_dir)

    env = {'PO_DIR': cls.po_dir, 'BUILD_DIR': cls.build_dir}
    process_utils.Spawn(['make', '-C', SCRIPT_DIR, 'build'],
                        ignore_stdout=True, ignore_stderr=True,
                        env=env, check_call=True)

    translation.LOCALES = [translation.DEFAULT_LOCALE] + [
        os.path.splitext(os.path.basename(po_file))[0] for po_file in po_files]
    translation.LOCALE_DIR = cls.locale_dir

  @classmethod
  def tearDownClass(cls):
    if os.path.exists(cls.temp_dir):
      shutil.rmtree(cls.temp_dir)

  def setUp(self):
    self.formatter = string.Formatter()
    self.errors = []

  def tearDown(self):
    if self.errors:
      raise AssertionError('\n'.join(self.errors).encode('UTF-8'))

  def AddError(self, err):
    self.errors.append(err)

  def testFormatStringVariablesMatch(self):
    all_translations = translation.GetAllTranslations()

    for text in all_translations:
      default_text = text[translation.DEFAULT_LOCALE]
      default_vars = self._ExtractVariablesFromFormatString(
          default_text, translation.DEFAULT_LOCALE)
      for locale in translation.LOCALES:
        if locale == translation.DEFAULT_LOCALE:
          continue
        used_vars = self._ExtractVariablesFromFormatString(text[locale], locale)
        unknown_vars = used_vars - default_vars
        if unknown_vars:
          self.AddError(f'[{locale}] "{text[locale]}": Unknown vars '
                        f'{list(unknown_vars)!r}')

        unused_vars = default_vars - used_vars
        if unused_vars:
          logging.warning('[%s] "%s": Unused vars %r', locale, text[locale],
                          list(unused_vars))

  def testFormatStringFormat(self):
    all_translations = translation.GetAllTranslations()

    kwargs = collections.defaultdict(_MockValue)
    for text in all_translations:
      for locale in translation.LOCALES:
        try:
          self.formatter.vformat(text[locale], [], kwargs)
        except Exception as e:
          self.AddError(f'[{locale}] "{text[locale]}": {e}')

  def _ExtractVariablesFromFormatString(self, format_str, locale):
    ret = set()
    for unused_text, field_name, unused_format_spec, unused_conversion in (
        self.formatter.parse(format_str)):
      if field_name is None:
        continue
      var_name = re.match('[a-zA-Z0-9_]*', field_name).group(0)
      if not var_name or re.match('[0-9]+$', var_name):
        self.AddError(
            f'[{locale}] "{format_str}": Positional argument {{{var_name}}} '
            'found')
      else:
        ret.add(var_name)
    return ret


class PoCheckTest(unittest.TestCase):
  """Check some formatting issue for po files."""
  def setUp(self):
    self.po_files = glob.glob(os.path.join(SCRIPT_DIR, '*.po'))

  def testNoFuzzy(self):
    err_files = []
    for po_file in self.po_files:
      po_lines = file_utils.ReadLines(po_file)
      if any(line.startswith('#, fuzzy') for line in po_lines):
        err_files.append(os.path.basename(po_file))

    self.assertFalse(
        err_files,
        f"'#, fuzzy' lines found in files {err_files!r}, please check the "
        "translation is correct and remove those lines.")

  def testNoUnused(self):
    err_files = []
    for po_file in self.po_files:
      po_lines = file_utils.ReadLines(po_file)
      if any(line.startswith('#~') for line in po_lines):
        err_files.append(os.path.basename(po_file))

    self.assertFalse(
        err_files,
        f"Lines started with '#~' found in files {err_files!r}, please check "
        "if those lines are unused and remove those lines.")

  def testNoUnusedAgain(self):
    bad_lines = []
    for po_file in self.po_files:
      po_lines = file_utils.ReadLines(po_file)
      base_po_file = os.path.basename(po_file)
      last_line = ''
      is_first_msgid = True
      for line_number, line in enumerate(po_lines, 1):
        if line.startswith('msgid '):
          # Since po file always maps the first string to the header data and
          # the line before it can be any string, we skip the first msgid.
          # After the first msgid, every line before a msgid should start with
          # '#:' and contain the file reference it.
          if not is_first_msgid and not last_line.startswith('#:'):
            bad_lines.append((base_po_file, line_number))
          is_first_msgid = False
        last_line = line

    bad_lines_desc = (
        f'{po_file} at line {line_num}' for po_file, line_num in bad_lines)
    self.assertFalse(
        bad_lines,
        f'Translations without file reference found in {bad_lines_desc}, '
        'please check if those lines are unused and remove those lines.')


if __name__ == '__main__':
  unittest.main()
