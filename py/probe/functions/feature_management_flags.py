# Copyright 2023 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

from cros.factory.probe.lib import probe_function
from cros.factory.test import device_data

from cros.factory.external.chromeos_cli import gsctool as gsctool_module

class FeatureManagementFlagsFunction(probe_function.ProbeFunction):
  """Probes the feature management flags."""

  def __init__(self, **kwargs):
    super().__init__(**kwargs)
    self._gsctool = gsctool_module.GSCTool()

  # TODO(stevesu): The current formal way of checking BoardID is to leverage
  # `Gooftool.Core.IsCr50BoardIDSet()` however this complicates the whole
  # issue as when probing we shouldn't care about the correctness of
  # the RLZ code and we probably should not make the probe depends on the
  # Gooftool as well. Requires a refactor to put below `IsBoardIDSet` function
  # into gsctool and modify `Gooftool.Core.IsCr50BoardIDSet()` accordingly.
  # Should be part of the work related with b/279136124.
  def IsBoardIDSet(self):
    try:
      board_id = self._gsctool.GetBoardID()
    except gsctool_module.GSCToolError as e:
      raise RuntimeError(
          f'Failed to get boardID with gsctool command: {e!r}') from None
    if board_id.type == 0xffffffff:
      return False
    return True

  def Probe(self):

    chassis_branded = False
    hw_compliance_version = 0

    # In factory, in cases where board ID already set, treat the feature
    # flags collected from GSC vendor command as source of truth.
    # Otherwise, if either device data related with feature flags is None,
    # return a valid default value pair (False, 0) for HWID to work.
    if self.IsBoardIDSet():
      feature_flags_gsc = self._gsctool.GetFeatureManagementFlags()
      chassis_branded = feature_flags_gsc.is_chassis_branded
      hw_compliance_version = feature_flags_gsc.hw_compliance_version
    else:
      chassis_branded_device_data = device_data.GetDeviceData(
          device_data.KEY_FM_CHASSIS_BRANDED)
      hw_compliance_version_device_data = device_data.GetDeviceData(
          device_data.KEY_FM_HW_COMPLIANCE_VERSION)

      if (chassis_branded_device_data is not None and
          hw_compliance_version_device_data is not None):
        chassis_branded = chassis_branded_device_data
        hw_compliance_version = hw_compliance_version_device_data

    results = [{
        'is_chassis_branded': str(int(chassis_branded)),
        'hw_compliance_version': str(hw_compliance_version)
    }]

    return results
