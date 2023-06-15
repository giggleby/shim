# Copyright 2021 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

from cros.factory.probe.lib import probe_function
from cros.factory.probe.runtime_probe import runtime_probe_adapter
from cros.factory.utils import arg_utils


def CreateRuntimeProbeFunction(probe_function_name, args):
  """Create a runtime probe function.

  While evaluation, the function proxies the argument to runtime probe and
  return its result.

  Args:
    probe_function_name: runtime probe function name to be called.
    args: See cros.factory.probe.Function.ARGS.
  Returns:
    A class derived from probe_function.ProbeFunction to run the runtime probe
    function.
  """

  class RuntimeProbeFunction(probe_function.ProbeFunction):
    FUNCTION_NAME = probe_function_name
    ARGS = args

    def Probe(self):
      return runtime_probe_adapter.RunProbeFunction(self.FUNCTION_NAME,
                                                    self.args.ToDict())

  return RuntimeProbeFunction


def GetAllFunctions():
  """Returns all runtime probe functions.
  """
  return [
      CreateRuntimeProbeFunction('generic_battery', []),
      CreateRuntimeProbeFunction('generic_camera', []),
      CreateRuntimeProbeFunction('generic_storage', []),
      CreateRuntimeProbeFunction('gpu', []),
      CreateRuntimeProbeFunction('mmc_host', [
          arg_utils.Arg(
              'is_emmc_attached', bool,
              'Only fetches the devices match the emmc attached state',
              default=None),
      ]),
      CreateRuntimeProbeFunction('tcpc', []),
  ]
