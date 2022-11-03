# Copyright 2021 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

import functools
import hashlib
import logging
import textwrap
from typing import List, Optional, Tuple

import yaml


from cros.chromeoshwid import update_checksum  # isort: split

from cros.factory.hwid.service.appengine.data.converter import converter_utils
from cros.factory.hwid.service.appengine.data import hwid_db_data
from cros.factory.hwid.service.appengine import hwid_action
from cros.factory.hwid.service.appengine import hwid_preproc_data
from cros.factory.hwid.service.appengine import hwid_validator
from cros.factory.hwid.service.appengine.proto import hwid_api_messages_pb2  # pylint: disable=no-name-in-module
from cros.factory.hwid.v3 import common
from cros.factory.hwid.v3 import contents_analyzer
from cros.factory.hwid.v3 import database
from cros.factory.probe_info_service.app_engine import bundle_builder


_HWID_BUNDLE_INSTALLER_NAME = 'install.py'
_HWID_BUNDLE_INSTALLER_SCRIPT = textwrap.dedent(f"""\
    #!/usr/bin/env python
    import os
    import os.path
    import shutil
    import sys
    srcdir = os.path.dirname(os.path.join(os.getcwd(), __file__))
    dstdir = sys.argv[1] if len(sys.argv) > 1 else '/usr/local/factory/hwid'
    if os.path.exists(dstdir):
      if not os.path.isdir(dstdir):
        sys.exit('The destination %r is not a directory.' % dstdir)
    else:
      os.makedirs(dstdir)
    for f in os.listdir(srcdir):
      if f == '{_HWID_BUNDLE_INSTALLER_NAME}':
        continue
      shutil.copyfile(os.path.join(srcdir, f), os.path.join(dstdir, f))
    """)


def _GetFullHWIDDBAndChangeFingerprint(curr_hwid_db_contents,
                                       new_hwid_db_editable_section):
  new_hwid_db_editable_section = _NormalizeAndJoinHWIDDBEditableSectionLines(
      new_hwid_db_editable_section.splitlines())
  curr_header, unused_curr_editable_section_lines = _SplitHWIDDBV3Sections(
      curr_hwid_db_contents)
  new_hwid_db_contents = update_checksum.ReplaceChecksum(
      f'{curr_header}\n{new_hwid_db_editable_section}\n')
  checksum = ''
  for contents in (curr_hwid_db_contents, new_hwid_db_contents):
    checksum = hashlib.sha1((checksum + contents).encode('utf-8')).hexdigest()
  return (new_hwid_db_contents, checksum)


def _SplitHWIDDBV3Sections(full_hwid_db_contents) -> Tuple[str, List[str]]:
  """Split the given HWID DB contents into the header and lines of DB body."""
  lines = full_hwid_db_contents.splitlines()
  split_idx_list = [i for i, l in enumerate(lines) if l.rstrip() == 'image_id:']
  if len(split_idx_list) != 1:
    logging.error('Got an unexpected HWID DB: %r', full_hwid_db_contents)
    raise hwid_action.HWIDActionError('The project has an invalid HWID DB.')
  return '\n'.join(lines[:split_idx_list[0]]), lines[split_idx_list[0]:]


def _NormalizeAndJoinHWIDDBEditableSectionLines(lines):
  return '\n'.join(l.rstrip() for l in lines).rstrip()


class HWIDV3SelfServiceActionHelper:

  def __init__(self, hwid_v3_preproc_data: hwid_preproc_data.HWIDV3PreprocData):
    self._preproc_data = hwid_v3_preproc_data

    self._hwid_validator = hwid_validator.HwidValidator()

  def GetDBEditableSection(self, suppress_support_status=False,
                           internal=False) -> str:
    dumped_db = self._preproc_data.database.DumpDataWithoutChecksum(
        suppress_support_status=suppress_support_status, internal=internal)
    return self.RemoveHeader(dumped_db)

  def PatchFirmwareBundleUUIDs(
      self,
      internal_db_content: hwid_db_data.HWIDDBData) -> hwid_db_data.HWIDDBData:
    """Patches existing bundle UUIDs from internal HWID DB in repo."""

    old_db = database.Database.LoadData(
        self._preproc_data.raw_database_internal)
    new_db = database.Database.LoadData(internal_db_content)
    for comp_cls in common.FirmwareComps:
      new_db_components = new_db.GetComponents(comp_cls)
      # TODO: disable renaming fw related components as bundle_uuids will be
      # lost.
      for comp_name, comp_info in old_db.GetComponents(comp_cls).items():
        if comp_info.bundle_uuids and comp_name in new_db_components:
          new_db.SetBundleUUIDs(comp_cls, comp_name, comp_info.bundle_uuids)
    return self.PatchHeader(
        new_db.DumpDataWithoutChecksum(internal=True,
                                       suppress_support_status=False))

  def AnalyzeDraftDBEditableSection(
      self, draft_db_editable_section: hwid_db_data.HWIDDBData,
      derive_fingerprint_only: bool, require_hwid_db_lines: bool,
      internal: bool = False,
      avl_converter_manager: Optional[converter_utils.ConverterManager] = None,
      avl_resource: Optional[
          hwid_api_messages_pb2.HwidDbExternalResource] = None
  ) -> hwid_action.DBEditableSectionAnalysisReport:
    curr_hwid_db_contents_external = self._preproc_data.raw_database
    curr_hwid_db_contents_internal = self._preproc_data.raw_database_internal

    new_hwid_db_contents_external, fingerprint = (
        _GetFullHWIDDBAndChangeFingerprint(curr_hwid_db_contents_external,
                                           draft_db_editable_section))
    new_hwid_db_contents_internal = None
    new_hwid_db_contents_external_normalized = ''
    noop_for_external_db = False

    # Try to normalize the input by loading and dumping.
    try:
      new_db = database.Database.LoadData(new_hwid_db_contents_external)
      new_db_dumped = new_db.DumpDataWithoutChecksum(
          suppress_support_status=False)
      # Check if the the change is no-op for external DB.
      noop_for_external_db = (
          new_db_dumped == self._preproc_data.database.DumpDataWithoutChecksum(
              suppress_support_status=False))

      draft_db_editable_section = self.RemoveHeader(new_db_dumped)
      new_hwid_db_contents_external_normalized, unused_fingerprint = (
          _GetFullHWIDDBAndChangeFingerprint(curr_hwid_db_contents_external,
                                             draft_db_editable_section))
    except (common.HWIDException, yaml.error.YAMLError):
      pass

    if internal:
      new_hwid_db_contents = new_hwid_db_contents_internal = (
          self.ConvertToInternalHWIDDBContent(avl_converter_manager,
                                              new_hwid_db_contents_external,
                                              avl_resource))
      curr_hwid_db_contents = curr_hwid_db_contents_internal
    else:
      new_hwid_db_contents = new_hwid_db_contents_external
      curr_hwid_db_contents = curr_hwid_db_contents_external

    report_factory = functools.partial(
        hwid_action.DBEditableSectionAnalysisReport, fingerprint,
        new_hwid_db_contents_external_normalized, new_hwid_db_contents_internal,
        noop_for_external_db)

    if derive_fingerprint_only:
      return report_factory([], [], [], {})

    try:
      self._hwid_validator.ValidateChange(new_hwid_db_contents,
                                          curr_hwid_db_contents)
    except hwid_validator.ValidationError as ex:
      return report_factory(ex.errors, [], [], {})

    analyzer = contents_analyzer.ContentsAnalyzer(new_hwid_db_contents, None,
                                                  curr_hwid_db_contents)
    analysis = analyzer.AnalyzeChange(self.RemoveHeader, require_hwid_db_lines)
    return report_factory([], analysis.precondition_errors, analysis.lines,
                          analysis.hwid_components, analysis.touched_sections)

  def GetHWIDBundleResourceInfo(
      self, fingerprint_only) -> hwid_action.BundleResourceInfo:
    # TODO: Remove entire method along with GetHwidBundleResourceInfo API
    fingerprint = hashlib.sha1(
        self._preproc_data.raw_database.encode('utf-8')).hexdigest()
    if fingerprint_only:
      return hwid_action.BundleResourceInfo(fingerprint, None)
    return hwid_action.BundleResourceInfo(fingerprint, {})

  def BundleHWIDDB(self):
    builder = bundle_builder.BundleBuilder()
    internal_db = self._preproc_data.database
    tag_trimmed_raw_db = internal_db.DumpDataWithoutChecksum(
        suppress_support_status=True, internal=False)
    external_raw_db = self.PatchHeader(tag_trimmed_raw_db)
    checksum = database.Database.ChecksumForText(external_raw_db)

    builder.AddRegularFile(internal_db.project, external_raw_db.encode('utf-8'))
    builder.AddExecutableFile(_HWID_BUNDLE_INSTALLER_NAME,
                              _HWID_BUNDLE_INSTALLER_SCRIPT.encode('utf-8'))
    builder.SetRunnerFilePath(_HWID_BUNDLE_INSTALLER_NAME)

    # TODO(b/211957606) remove this stopgap which shows the HWID DB checksum for
    # cros_payload.sh to parse.
    # pylint: disable=protected-access
    builder._SetStopGapHWIDDBChecksum(checksum)
    # pylint: enable=protected-access
    builder.hwid_db_commit_id = self._preproc_data.hwid_db_commit_id
    return hwid_action.BundleInfo(builder.Build(), builder.FILE_NAME_EXT[1:])

  def PatchHeader(
      self,
      hwid_db_content: hwid_db_data.HWIDDBData) -> hwid_db_data.HWIDDBData:
    hwid_db_editable_section = self.RemoveHeader(hwid_db_content)
    patched_hwid_db_content, unused_checksum = (
        _GetFullHWIDDBAndChangeFingerprint(self._preproc_data.raw_database,
                                           hwid_db_editable_section))
    return patched_hwid_db_content

  @staticmethod
  def RemoveHeader(hwid_db_contents):
    unused_header, lines = _SplitHWIDDBV3Sections(hwid_db_contents)
    return _NormalizeAndJoinHWIDDBEditableSectionLines(lines)

  def ConvertToInternalHWIDDBContent(
      self, avl_converter_manager: converter_utils.ConverterManager,
      hwid_db_contents: hwid_db_data.HWIDDBData,
      avl_resource: hwid_api_messages_pb2.HwidDbExternalResource
  ) -> hwid_db_data.HWIDDBData:

    hwid_db_editable_contents_with_avl = avl_converter_manager.LinkAVL(
        hwid_db_contents, avl_resource)
    new_hwid_db_contents_internal_without_bundle = self.PatchHeader(
        hwid_db_editable_contents_with_avl)
    return self.PatchFirmwareBundleUUIDs(
        new_hwid_db_contents_internal_without_bundle)
