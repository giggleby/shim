#!/usr/bin/env python3
#
# Copyright 2017 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.


"""The unittest that use closure compiler to catch common error in goofy.js."""

import os
import re
import subprocess
from typing import Any, Dict, List
import unittest

from cros.factory.unittest_utils import label_utils


SCRIPT_DIR = os.path.dirname(__file__)
# The type of DESCRIPTION_ALLOW_LIST is Tuple[re.Pattern]. It's defined after
# python3.8.
DESCRIPTION_ALLOW_LIST = ()
KEY_ALLOW_LIST = (
    'JSC_DEPRECATED_PROP_REASON',
    'JSC_INEXISTENT_PROPERTY',
    'JSC_INTERFACE_CONSTRUCTOR_SHOULD_NOT_TAKE_ARGS',
    'JSC_MISSING_CONST_PROPERTY',
    'JSC_MISSING_NULLABILITY_MODIFIER_JSDOC',
    'JSC_POSSIBLE_INEXISTENT_PROPERTY',
    'JSC_REDUNDANT_NULLABILITY_MODIFIER_JSDOC',
    'JSC_TYPE_MISMATCH',
    'JSC_USE_OF_GOOG_PROVIDE',
    'JSC_VAR',
)
_closure_error_pattern = re.compile(
    r'(?P<source>[^:]*):(?:(?P<line>.*):)?(?:(?P<column>.*):)? '
    r'(?P<level>.*) -(?: \[(?P<key>.*)\])? (?P<description>.*)')


def FormatWarning(warning: Dict[str, Any]):
  output_list = []

  source = warning['source']
  output_list.append(f'{source}:')

  line = warning['line']
  if line is not None:
    output_list.append(f'{line}:')

  column = warning['column']
  if column is not None:
    output_list.append(f'{column}:')

  level = warning['level']
  description = warning['description']
  output_list.append(f' {level} -')

  key = warning['key']
  if key is not None:
    output_list.append(f' [{key}]')

  output_list.append(f' {description}\n')
  return ''.join(output_list)


def FormatWarnings(warnings):
  return ''.join(FormatWarning(warning) for warning in warnings)


def ParseClosureWarnings(stderr: str) -> List[Dict[str, Any]]:
  """Parses the stderr from closure-compiler.

  Output examples:
    1. `goofy.js:1:2: WARNING - [JSC_UNRECOGNIZED_TYPE_ERROR] Bad type`

  Args:
    stderr: The stderr from closure-compiler.

  Returns:
    A list of dictionary of the component of warnings.
  """
  warnings = []
  for line in stderr.splitlines():
    match = _closure_error_pattern.fullmatch(line)
    if match:
      warnings.append(match.groupdict())
  return warnings


# TODO (b/204838120)
@label_utils.Informational
class GoofyJSTest(unittest.TestCase):

  def runTest(self):
    static_dir = os.path.join(SCRIPT_DIR, '..', 'static')
    result = subprocess.run(['make', '-C', static_dir, 'check_js'],
                            stderr=subprocess.PIPE, encoding='utf8',
                            check=False)
    warnings = ParseClosureWarnings(result.stderr)

    filtered_warnings = []
    critical_warnings = []
    for warning in warnings:
      description = warning.get('description')
      if (description and any(
          pattern.fullmatch(description)
          for pattern in DESCRIPTION_ALLOW_LIST)):
        filtered_warnings.append(warning)
        continue
      key = warning.get('key')
      if key and key in KEY_ALLOW_LIST:
        filtered_warnings.append(warning)
        continue

      critical_warnings.append(warning)

    if filtered_warnings:
      print('filtered warnings:')
      print(FormatWarnings(filtered_warnings))

    if critical_warnings or result.returncode != 0:
      self.fail("There's warning in closure compiler output, please fix them.\n"
                f'return_code:{result.returncode}\n'
                f'critical warnings:\n{FormatWarnings(critical_warnings)}')


if __name__ == '__main__':
  unittest.main()
