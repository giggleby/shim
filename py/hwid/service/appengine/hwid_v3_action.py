# Copyright 2021 The Chromium OS Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.
"""Defines available actions for HWIDv3 DB."""

import logging
from typing import List, Optional

from cros.factory.hwid.service.appengine.data.converter import converter_utils
from cros.factory.hwid.service.appengine.data import hwid_db_data
from cros.factory.hwid.service.appengine import hwid_action
from cros.factory.hwid.service.appengine.hwid_action_helpers import v3_self_service_helper as ss_helper_module
from cros.factory.hwid.service.appengine import hwid_preproc_data
from cros.factory.hwid.service.appengine.proto import hwid_api_messages_pb2  # pylint: disable=no-name-in-module
from cros.factory.hwid.service.appengine import verification_payload_generator_config as vpg_config_module
from cros.factory.hwid.v3 import common
from cros.factory.hwid.v3 import hwid_utils


class HWIDV3Action(hwid_action.HWIDAction):
  HWID_VERSION = 3

  def __init__(self, hwid_v3_preproc_data: hwid_preproc_data.HWIDV3PreprocData):
    self._preproc_data = hwid_v3_preproc_data
    self._ss_helper = (
        ss_helper_module.HWIDV3SelfServiceActionHelper(self._preproc_data))

  def GetBOMAndConfigless(
      self, hwid_string: str, verbose: Optional[bool] = False,
      vpg_config: Optional[
          vpg_config_module.VerificationPayloadGeneratorConfig] = None,
      require_vp_info: Optional[bool] = False):
    try:
      hwid, _bom, configless = hwid_utils.DecodeHWID(
          self._preproc_data.database, hwid_string)
    except common.HWIDException as e:
      logging.info('Unable to decode a valid HWID. %s', hwid_string)
      raise hwid_action.InvalidHWIDError('HWID not found %s' % hwid_string, e)

    bom = hwid_action.BOM()

    bom.AddAllComponents(_bom.components, self._preproc_data.database,
                         verbose=verbose, vpg_config=vpg_config,
                         require_vp_info=require_vp_info)
    bom.phase = self._preproc_data.database.GetImageName(hwid.image_id)
    bom.project = hwid.project

    return bom, configless

  def GetDBV3(self):
    return self._preproc_data.database

  def GetDBEditableSection(self):
    return self._ss_helper.GetDBEditableSection()

  def AnalyzeDraftDBEditableSection(
      self, draft_db_editable_section: hwid_db_data.HWIDDBData,
      derive_fingerprint_only: bool, require_hwid_db_lines: bool,
      internal: bool = False,
      avl_converter_manager: Optional[converter_utils.ConverterManager] = None,
      avl_resource: Optional[
          hwid_api_messages_pb2.HwidDbExternalResource] = None
  ) -> hwid_action.DBEditableSectionAnalysisReport:
    return self._ss_helper.AnalyzeDraftDBEditableSection(
        draft_db_editable_section, derive_fingerprint_only,
        require_hwid_db_lines, internal, avl_converter_manager, avl_resource)

  def GetHWIDBundleResourceInfo(self, fingerprint_only=False):
    return self._ss_helper.GetHWIDBundleResourceInfo(fingerprint_only)

  def BundleHWIDDB(self):
    return self._ss_helper.BundleHWIDDB()

  def RemoveHeader(self, hwid_db_contents):
    return self._ss_helper.RemoveHeader(hwid_db_contents)

  def PatchHeader(self, hwid_db_content: hwid_db_data.HWIDDBData):
    return self._ss_helper.PatchHeader(hwid_db_content)

  def GetComponents(self, with_classes: Optional[List[str]] = None):
    comps = {}
    database = self.GetDBV3()
    with_classes = with_classes or database.GetComponentClasses()
    for comp_cls in with_classes:
      comps[comp_cls] = database.GetComponents(comp_cls)
    return comps
