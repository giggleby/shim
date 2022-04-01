# Copyright 2021 The Chromium OS Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.
"""Utilities for controlling unittest run tag"""

import os
import unittest

SKIP_INFORMATIONAL_ENV = 'SKIP_INFORMATIONAL'
ENV_TRUE = str(True)
ENV_FALSE = str(False)


def Informational(test_function):
  """Decorator to set test as informational."""
  return unittest.skipIf(
      os.getenv(SKIP_INFORMATIONAL_ENV) == ENV_TRUE,
      f'{SKIP_INFORMATIONAL_ENV} sets to {ENV_TRUE} explicitly')(
          test_function)


def SetSkipInformational(skip):
  os.environ[SKIP_INFORMATIONAL_ENV] = ENV_TRUE if skip else ENV_FALSE
