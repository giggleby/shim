# Copyright 2019 The Chromium OS Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

import re

import factory_common  # pylint: disable=unused-import
from cros.factory.probe.lib import cached_probe_function
from cros.factory.utils import process_utils

class GenericRLZFunction(cached_probe_function.CachedProbeFunction):
  """Probe the generic rlz information."""

  def GetCategoryFromArgs(self):
    return None

  @classmethod
  def ProbeAllDevices(cls):
    rlz_code = process_utils.CheckOutput(
        ['mosys', 'platform', 'brand'])
    rlz_code = rlz_code.replace('\n', '')
    if not re.match(r'^[A-Z]{4}$', rlz_code):
      return None
    return [{'rlz_code':rlz_code}]
