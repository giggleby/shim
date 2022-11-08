# Copyright 2021 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

from cros.factory.probe.runtime_probe import probe_config_definition
from cros.factory.probe.runtime_probe import probe_config_types
from cros.factory.utils import json_utils
from cros.factory.utils import process_utils

RUNTIME_PROBE_BIN = '/usr/local/usr/bin/factory_runtime_probe'
COMPONENT_NAME = 'adaptor_component'


def RunProbeFunction(category, probe_function_name, args):
  definition = probe_config_definition.GetProbeStatementDefinition(category)
  probe_statement = definition.GenerateProbeStatement(
      COMPONENT_NAME, probe_function_name, {}, args)
  payload = probe_config_types.ProbeConfigPayload()
  payload.AddComponentProbeStatement(probe_statement)

  output = process_utils.CheckOutput(
      [RUNTIME_PROBE_BIN, payload.DumpToString()])
  res = json_utils.LoadStr(output)
  return [x['values'] for x in res[category]]
