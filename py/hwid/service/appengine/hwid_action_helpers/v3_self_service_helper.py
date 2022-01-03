# Copyright 2021 The Chromium OS Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

import functools
import hashlib
import logging
import textwrap
from typing import List, Tuple

from cros.chromeoshwid import update_checksum
from cros.factory.hwid.service.appengine import hwid_action
from cros.factory.hwid.service.appengine import hwid_preproc_data
from cros.factory.hwid.service.appengine import hwid_validator
from cros.factory.hwid.v3 import contents_analyzer
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

  def GetDBEditableSection(self) -> str:
    full_hwid_db_contents = self._preproc_data.raw_database
    unused_header, lines = _SplitHWIDDBV3Sections(full_hwid_db_contents)
    return _NormalizeAndJoinHWIDDBEditableSectionLines(lines)

  def ReviewDraftDBEditableSection(
      self, draft_db_editable_section,
      derive_fingerprint_only=False) -> hwid_action.DBEditableSectionChangeInfo:
    curr_hwid_db_contents = self._preproc_data.raw_database
    new_hwid_db_contents, fingerprint = _GetFullHWIDDBAndChangeFingerprint(
        curr_hwid_db_contents, draft_db_editable_section)
    change_info_factory = functools.partial(
        hwid_action.DBEditableSectionChangeInfo, fingerprint,
        new_hwid_db_contents)
    if derive_fingerprint_only:
      return change_info_factory(None, None)

    try:
      unused_model, new_hwid_comps = self._hwid_validator.ValidateChange(
          new_hwid_db_contents, curr_hwid_db_contents)
    except hwid_validator.ValidationError as ex:
      return change_info_factory(ex.errors, None)

    return change_info_factory([], new_hwid_comps)

  def AnalyzeDraftDBEditableSection(
      self,
      draft_db_editable_section) -> hwid_action.DBEditableSectionAnalysisReport:
    curr_hwid_db_contents = self._preproc_data.raw_database
    new_hwid_db_contents, unused_fp = _GetFullHWIDDBAndChangeFingerprint(
        curr_hwid_db_contents, draft_db_editable_section)

    analyzer = contents_analyzer.ContentsAnalyzer(new_hwid_db_contents, None,
                                                  curr_hwid_db_contents)
    return analyzer.AnalyzeChange(self.RemoveHeader)

  def GetHWIDBundleResourceInfo(self, fingerprint_only):
    del fingerprint_only
    return hwid_action.BundleResourceInfo(
        fingerprint=hashlib.sha1(
            self._preproc_data.raw_database.encode('utf-8')).hexdigest())

  def BundleHWIDDB(self):
    builder = bundle_builder.BundleBuilder()
    builder.AddRegularFile(self._preproc_data.project.upper(),
                           self._preproc_data.raw_database.encode('utf-8'))
    builder.AddExecutableFile(_HWID_BUNDLE_INSTALLER_NAME,
                              _HWID_BUNDLE_INSTALLER_SCRIPT.encode('utf-8'))
    builder.SetRunnerFilePath(_HWID_BUNDLE_INSTALLER_NAME)

    # TODO(b/211957606) remove this stopgap which shows the HWID DB checksum for
    # cros_payload.sh to parse.
    # pylint: disable=protected-access
    builder._SetStopGapHWIDDBChecksum(self._preproc_data.database.checksum)
    # pylint: enable=protected-access
    return hwid_action.BundleInfo(builder.Build(), builder.FILE_NAME_EXT[1:])

  @staticmethod
  def RemoveHeader(hwid_db_contents):
    unused_header, lines = _SplitHWIDDBV3Sections(hwid_db_contents)
    return _NormalizeAndJoinHWIDDBEditableSectionLines(lines)
