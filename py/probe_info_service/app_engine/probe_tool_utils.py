# Copyright 2023 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

from cros.factory.probe_info_service.app_engine import probe_info_analytics
from cros.factory.probe_info_service.app_engine.probe_tools import analyzers
from cros.factory.probe_info_service.app_engine.probe_tools import probe_statement_converters


def CreateProbeInfoAnalyzer() -> probe_info_analytics.IProbeInfoAnalyzer:
  return analyzers.ProbeInfoAnalyzer(
      probe_statement_converters.GetAllConverters())
