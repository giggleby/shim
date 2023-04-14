#!/usr/bin/env python3
#
# Copyright 2014 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.


"""Ensures that factory documentation can be built properly."""


import os
import pprint
import re
import sys
import unittest

from cros.factory.test.env import paths
from cros.factory.unittest_utils import label_utils
from cros.factory.utils.process_utils import Spawn


# Files allowed to have errors now.
BLOCKLIST = []
RSTS_BLOCKLIST = []


# TODO (b/204837610)
@label_utils.Informational
class DocTest(unittest.TestCase):
  """Tests the overall documentation generation process."""

  def testMakeDoc(self):
    stderr_lines = Spawn(
        ['make', 'doc'], cwd=paths.FACTORY_DIR,
        check_output=True, read_stderr=True,
        log=True, log_stderr_on_error=True).stderr_lines()

    files_with_errors = set()
    rsts_with_errors = set()

    for l in stderr_lines:
      match = re.match(r'(([^:]+):)*(\d+): (ERROR|WARNING|SEVERE): (.+)',
                       l.strip())

      if match:
        basename = os.path.basename(match.group(1))
        blocklisted = basename in BLOCKLIST
        sys.stderr.write(
            f"{l.strip()}{' (blocklisted)' if blocklisted else ''}\n")
        files_with_errors.add(basename)
        continue

      match = re.fullmatch(
          r'ERROR:root:Failed to generate document for pytest (.+)\.',
          l.strip())

      if match:
        blocklisted = match.group(1) in RSTS_BLOCKLIST
        sys.stderr.write(
            f"{l.strip()}{' (blocklisted)' if blocklisted else ''}\n")
        rsts_with_errors.add(match.group(1))

    if files_with_errors:
      # pprint for easy copy/paste to BLOCKLIST
      sys.stderr.write('Files with errors:\n')
      pprint.pprint(sorted(files_with_errors), sys.stderr)

    if rsts_with_errors:
      # pprint for easy copy/paste to RSTS_BLOCKLIST
      sys.stderr.write('generate_rsts with errors:\n')
      pprint.pprint(sorted(rsts_with_errors), sys.stderr)

    error_messages = []
    failed_files = files_with_errors - set(BLOCKLIST)
    if failed_files:
      error_messages.append(
          f'Found errors in non-blocklisted files {sorted(failed_files)}; see '
          'stderr for details')

    failed_rsts = rsts_with_errors - set(RSTS_BLOCKLIST)
    if failed_rsts:
      error_messages.append(
          f'Found errors in non-blocklisted pytests {sorted(failed_rsts)}; Run '
          '"bin/generate_rsts -o build/tmp/docsrc" for details')

    if error_messages:
      self.fail('\n'.join(error_messages))


if __name__ == '__main__':
  unittest.main()
