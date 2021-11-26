# Copyright 2021 The Chromium OS Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

import functools
import hashlib
import logging
from typing import List, Tuple

from cros.chromeoshwid import update_checksum
from cros.factory.hwid.service.appengine import hwid_action
from cros.factory.hwid.service.appengine import hwid_preproc_data
from cros.factory.hwid.service.appengine import hwid_validator
from cros.factory.hwid.v3 import contents_analyzer


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

    def _RemoveHeader(hwid_db_contents):
      unused_header, lines = _SplitHWIDDBV3Sections(hwid_db_contents)
      return _NormalizeAndJoinHWIDDBEditableSectionLines(lines)

    return analyzer.AnalyzeChange(_RemoveHeader)
