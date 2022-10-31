# Copyright 2022 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

from cros.factory.utils import file_utils
from cros.factory.utils import process_utils
from cros.factory.utils import type_utils


DEFAULT_GSC_CONSTANTS_PATH = '/usr/share/cros/gsc-constants.sh'
GSCTOOL_PATH = '/usr/sbin/gsctool'


class GSCUtilsError(type_utils.Error):
  message_template = 'Fail to load constant: %s.'

  def __init__(self, constant_name):
    type_utils.Error.__init__(self)
    self.constant_name = constant_name

  def __str__(self):
    return GSCUtilsError.message_template % self.constant_name


# TODO(phoebewang): Remove the workaround once there's way to distinguish the
# GSC.
class GSCUtils:
  """Gets Google security chip (GSC) related constants from GSC_CONSTANTS_PATH.

  Currently, there's no way to distinguish between H1 and DT.
  As a workaround, we read the file `gsc-constants.sh` to get the information
  of GSC. This file is generated in build time according to the USE flag.
  If both cr50_onboard and ti50_onboard are presented, then we assume the board
  is using DT.
  """

  def __init__(self, gsc_constants_path=DEFAULT_GSC_CONSTANTS_PATH):
    self.gsc_constants_path = gsc_constants_path
    file_utils.CheckPath(self.gsc_constants_path)

  def _GetConstant(self, constant_name):
    try:
      return process_utils.CheckOutput(
          f'. "{self.gsc_constants_path}"; "{constant_name}"', sudo=True,
          shell=True).strip()
    except process_utils.CalledProcessError as err:
      raise GSCUtilsError(constant_name) from err

  @type_utils.LazyProperty
  def name(self):
    return self._GetConstant('gsc_name')

  @type_utils.LazyProperty
  def image_base_name(self):
    return self._GetConstant('gsc_image_base_name')

  @type_utils.LazyProperty
  def metrics_prefix(self):
    return self._GetConstant('gsc_metrics_prefix')

  def IsTi50(self):
    return self.name == 'ti50'

  def GetGSCToolCmd(self):
    gsctool_cmd = [GSCTOOL_PATH]
    if self.IsTi50():
      gsctool_cmd.append('-D')
    return gsctool_cmd
