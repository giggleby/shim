#!/usr/bin/env python3
#
# Copyright 2014 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.


import codecs
import enum
import unittest
from unittest import mock

from cros.factory.doc import generate_rsts
from cros.factory.utils.arg_utils import Arg
from cros.factory.utils.file_utils import UnopenedTemporaryFile


class GenerateDocsTest(unittest.TestCase):

  def testGenerateTestDocs(self):
    # A class that looks like a test module.
    class PseudoModule:
      """Module-level help."""
      class FooTest(unittest.TestCase):
        ARGS = [
            Arg('a', int, 'A', default=1),
            Arg('b', enum.Enum('b', ['b1', 'b2']), 'Foo:\n'
                '\n'
                '  - bar\n'
                '  - baz\n', default='b1'),
        ]

        def runTest(self):
          pass

    with UnopenedTemporaryFile() as temp:
      with codecs.open(temp, 'w', 'utf-8') as out:
        with mock.patch(
            'cros.factory.test.utils.pytest_utils.LoadPytestModule') as lpm:
          lpm.return_value = PseudoModule

          generate_rsts.GenerateTestDocs(
              generate_rsts.RSTWriter(out), 'pseudo_test')

      with open(temp, encoding='utf8') as f:
        lines = f.read().splitlines()

        pseudo_url = ("https://chromium.googlesource.com/chromiumos/platform/fa"
                      "ctory/+/refs/heads/main/py/test/pytests/pseudo_test.py")
        pseudo_output = f"""pseudo_test
===========
**Source code:** `pseudo_test.py <{pseudo_url}>`_

Module-level help.

Test Arguments
--------------
.. list-table::
   :widths: 20 10 60
   :header-rows: 1
   :align: left

   * - Name
     - Type
     - Description

   * - a
     - int
     - (optional; default: ``1``) A

   * - b
     - ['b1', 'b2']
     - (optional; default: ``\'b1\'``) Foo:
       \n         - bar
         - baz
"""
      self.assertEqual(pseudo_output, '\n'.join(lines))


if __name__ == '__main__':
  unittest.main()
