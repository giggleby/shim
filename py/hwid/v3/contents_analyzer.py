# Copyright 2021 The Chromium OS Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.
"""This module collects utilities that analyze / validate the HWID DB contents.
"""

import copy
import difflib
import enum
import functools
import itertools
import logging
import re
from typing import Callable, Dict, List, NamedTuple, Optional

from cros.factory.hwid.v3 import common
from cros.factory.hwid.v3 import database
from cros.factory.hwid.v3 import name_pattern_adapter
from cros.factory.hwid.v3 import rule
from cros.factory.hwid.v3 import yaml_wrapper as yaml
from cros.factory.utils import schema

_BLOCKLIST_DRAM_TAG = set([
    'dram_default',
    'dram_placeholder',
    'a_fake_dram_0gb',
])


class ErrorCode(enum.Enum):
  """Enumerate the type of errors."""
  SCHEMA_ERROR = enum.auto()
  CONTENTS_ERROR = enum.auto()
  UNKNOWN_ERROR = enum.auto()
  COMPATIBLE_ERROR = enum.auto()


class Error(NamedTuple):
  """A record class to hold an error message."""
  code: ErrorCode
  message: str


class DiffStatus(NamedTuple):
  """Diff stats with the corresponding component in the previous DB."""
  unchanged: bool
  name_changed: bool
  support_status_changed: bool
  values_changed: bool
  prev_comp_name: str
  prev_support_status: str


ComponentNameInfo = name_pattern_adapter.NameInfo


class ValidationReport(NamedTuple):
  errors: List[Error]
  warnings: List[str]

  @classmethod
  def CreateEmpty(cls):
    return cls([], [])


class DBLineAnalysisResult(NamedTuple):

  class ModificationStatus(enum.Enum):
    NOT_MODIFIED = enum.auto()
    MODIFIED = enum.auto()
    NEWLY_ADDED = enum.auto()

  class Part(NamedTuple):

    class Type(enum.Enum):
      TEXT = enum.auto()
      COMPONENT_NAME = enum.auto()
      COMPONENT_STATUS = enum.auto()

    type: Type
    text: str

    @property
    def reference_id(self):
      return self.text  # Reuse the existing field.

  modification_status: ModificationStatus
  parts: List[Part]


class HWIDComponentAnalysisResult(NamedTuple):
  comp_cls: str
  comp_name: str
  support_status: str
  is_newly_added: bool
  comp_name_info: Optional[ComponentNameInfo]
  seq_no: int
  comp_name_with_correct_seq_no: Optional[str]
  null_values: bool
  diff_prev: Optional[DiffStatus]
  link_avl: bool


class ChangeAnalysis(NamedTuple):
  precondition_errors: List[Error]
  lines: List[DBLineAnalysisResult]
  hwid_components: Dict[str, HWIDComponentAnalysisResult]


class ContentsAnalyzer:

  class DBSnapshot(NamedTuple):
    """A record class that holds a specific version of HWID DB."""
    contents: str  # The raw string data.
    instance: Optional[database.Database]  # The loaded DB instance.
    load_error: Optional[Exception]  # Exception instance for loading failure.

  def __init__(self, curr_db_contents: str,
               expected_curr_db_checksum: Optional[str],
               prev_db_contents: Optional[str]):
    self._curr_db = self._LoadFromDBContents(curr_db_contents,
                                             expected_curr_db_checksum)
    self._prev_db = (
        self._LoadFromDBContents(prev_db_contents, None)
        if prev_db_contents is not None else None)

  @property
  def curr_db_instance(self) -> Optional[database.Database]:
    return self._curr_db.instance

  def ValidateIntegrity(self) -> ValidationReport:
    """Validates the current HWID DB."""
    report = ValidationReport.CreateEmpty()
    if self._curr_db.load_error:
      report.errors.append(
          Error(ErrorCode.SCHEMA_ERROR, str(self._curr_db.load_error)))
    else:
      for validation_func in [self._ValidateDramIntegrity]:
        keep_going = validation_func(report, self._curr_db.instance)
        if not keep_going:
          break
    return report

  def _ValidateDramIntegrity(self, validation_report, db_instance):
    for dram_tag, dram_info in db_instance.GetComponents('dram').items():
      if dram_tag in _BLOCKLIST_DRAM_TAG:
        continue
      if not dram_info.values or 'size' not in dram_info.values:
        validation_report.errors.append(
            Error(ErrorCode.CONTENTS_ERROR,
                  f'{dram_tag!r} does not contain size property'))
    return True

  def ValidateChange(self, ignore_invalid_old_db=False) -> ValidationReport:
    """Validates the change between the current HWID DB and the previous one."""
    report = ValidationReport.CreateEmpty()
    if self._curr_db.load_error:
      report.errors.append(
          Error(ErrorCode.SCHEMA_ERROR, str(self._curr_db.load_error)))
      return report

    if self._prev_db is None:
      if not self._ValidateChangeOfNewCreation(report):
        return report
    elif self._prev_db.load_error:
      if ignore_invalid_old_db:
        report.warnings.append(
            'The previous version of HWID database is an incompatible version '
            f'(exception: {self._prev_db.load_error}), ignore the pattern '
            'check.')
      else:
        report.errors.append(
            Error(
                ErrorCode.UNKNOWN_ERROR,
                'Failed to load the previous version of '
                f'HWID DB: {self._curr_db.load_error}'))
        return report
    else:
      if not self._ValidateChangeFromExistingSnapshot(report):
        return report
    self._ValidateChangeOfComponents(report)
    return report

  def _ValidateChangeOfNewCreation(self, report: ValidationReport) -> bool:
    """Checks if the newly created HWID DB applies up-to-date styles.

    Returns:
      A boolean indicates whether to keep performing the rest of validation
          steps.
    """
    if not self._curr_db.instance.can_encode:
      report.errors.append(
          Error(
              ErrorCode.CONTENTS_ERROR,
              'The new HWID database should not use legacy pattern.  Please '
              'use "hwid build-database" to prevent from generating legacy '
              'pattern.'))
      return False

    region_field_legacy_info = self._curr_db.instance.region_field_legacy_info
    if not region_field_legacy_info or any(region_field_legacy_info.values()):
      report.errors.append(
          Error(ErrorCode.CONTENTS_ERROR,
                'Legacy region field is forbidden in any new HWID database.'))
    return True

  def _ValidateChangeFromExistingSnapshot(self,
                                          report: ValidationReport) -> bool:
    """Checks if the HWID DB changes is backward compatible.

    Returns:
      A boolean indicates whether to keep performing the rest of validation
          steps.
    """
    # If the old database follows the new pattern rule, so does the new
    # database.
    if (self._prev_db.instance.can_encode and
        not self._curr_db.instance.can_encode):
      report.errors.append(
          Error(
              ErrorCode.COMPATIBLE_ERROR,
              'The new HWID database should not use legacy pattern. Please '
              'use "hwid update-database" to prevent from generating legacy '
              'pattern.'))
      return False

    # Make sure all the encoded fields in the existing patterns are not changed.
    for image_id in self._prev_db.instance.image_ids:
      old_bit_mapping = self._prev_db.instance.GetBitMapping(image_id=image_id)
      new_bit_mapping = self._curr_db.instance.GetBitMapping(image_id=image_id)
      for index, (element_old, element_new) in enumerate(
          zip(old_bit_mapping, new_bit_mapping)):
        if element_new != element_old:
          report.errors.append(
              Error(
                  ErrorCode.COMPATIBLE_ERROR,
                  f'Bit pattern mismatch found at bit {index} (encoded '
                  f'field={element_old[0]}). If you are trying to append new '
                  'bit(s), be sure to create a new bit pattern field instead '
                  'of simply incrementing the last field.'))

    old_reg_field_legacy_info = self._prev_db.instance.region_field_legacy_info
    new_reg_field_legacy_info = self._curr_db.instance.region_field_legacy_info
    for field_name, is_legacy_style in new_reg_field_legacy_info.items():
      orig_is_legacy_style = old_reg_field_legacy_info.get(field_name)
      if orig_is_legacy_style is None:
        if is_legacy_style:
          report.errors.append(
              Error(
                  ErrorCode.CONTENTS_ERROR,
                  'New region field should be constructed by new style yaml '
                  'tag.'))
      else:
        if orig_is_legacy_style != is_legacy_style:
          report.errors.append(
              Error(ErrorCode.COMPATIBLE_ERROR,
                    'Style of existing region field should remain unchanged.'))
    return True

  def _ValidateChangeOfComponents(self, report: ValidationReport):
    """Check if modified (created) component names are valid."""
    for comps in self._ExtractHWIDComponents().values():
      for comp in comps:
        if comp.extracted_seq_no is not None:
          expected_comp_name = ''.join([
              comp.extracted_noseq_comp_name, name_pattern_adapter.SEQ_SEP,
              str(comp.expected_seq_no)
          ])
          if expected_comp_name != comp.name:
            report.errors.append(
                Error(
                    ErrorCode.CONTENTS_ERROR,
                    'Invalid component name with sequence number, please '
                    f'modify it from {comp.name!r} to {expected_comp_name!r}'
                    '.'))

  def _AnalyzeDBLines(self, db_contents_patcher, all_placeholders,
                      db_placeholder_options):
    dumped_db_lines = db_contents_patcher(
        self._curr_db.instance.DumpDataWithoutChecksum(
            suppress_support_status=False,
            magic_placeholder_options=db_placeholder_options)).splitlines()

    no_placeholder_dumped_db_lines = db_contents_patcher(
        self._curr_db.instance.DumpDataWithoutChecksum(
            suppress_support_status=False)).splitlines()
    if len(dumped_db_lines) != len(no_placeholder_dumped_db_lines):
      # Unexpected case, skip deriving the line diffs.
      diff_view_line_it = itertools.repeat('  ', len(dumped_db_lines))
    elif not self._prev_db or not self._prev_db.instance:
      diff_view_line_it = itertools.repeat('  ', len(dumped_db_lines))
    else:
      prev_db_contents_lines = db_contents_patcher(
          self._prev_db.instance.DumpDataWithoutChecksum(
              suppress_support_status=False)).splitlines()
      diff_view_line_it = difflib.ndiff(
          prev_db_contents_lines, no_placeholder_dumped_db_lines, charjunk=None)

    removed_line_count = 0

    splitter = _LineSplitter(
        all_placeholders,
        functools.partial(DBLineAnalysisResult.Part,
                          DBLineAnalysisResult.Part.Type.TEXT))
    line_analysis_result = []
    for line in dumped_db_lines:
      while True:
        diff_view_line = next(diff_view_line_it)
        if diff_view_line.startswith('? '):
          continue
        if not diff_view_line.startswith('- '):
          break
        removed_line_count += 1
      if diff_view_line.startswith('  '):
        removed_line_count = 0
        mod_status = DBLineAnalysisResult.ModificationStatus.NOT_MODIFIED
      elif removed_line_count > 0:
        removed_line_count -= 1
        mod_status = DBLineAnalysisResult.ModificationStatus.MODIFIED
      else:
        mod_status = DBLineAnalysisResult.ModificationStatus.NEWLY_ADDED

      parts = splitter.SplitText(line)
      line_analysis_result.append(DBLineAnalysisResult(mod_status, parts))
    return line_analysis_result

  def AnalyzeChange(self, db_contents_patcher: Optional[Callable[[str], str]],
                    require_hwid_db_lines: bool) -> ChangeAnalysis:
    """Analyzes the HWID DB change.

    Args:
      db_contents_patcher: An optional function that patches / removes the
          header of the given HWID DB contents.  This argument is ignored when
          require_hwid_db_lines is False.
      require_hwid_db_lines: A flag indicating if DB line analysis is required.

    Returns:
      An instance of `ChangeAnalysis`.
    """
    report = ChangeAnalysis([], [], {})
    if not self._curr_db.instance:
      report.precondition_errors.append(
          Error(ErrorCode.SCHEMA_ERROR, str(self._curr_db.load_error)))
      return report

    # To locate the HWID component name / status text part in the HWID DB
    # contents, we first dump a specialized HWID DB which has all cared parts
    # replaced by some magic placeholders.  Then we parse the raw string to
    # find out the location of those fields.

    all_comps = self._ExtractHWIDComponents()
    all_placeholders = {}
    db_placeholder_options = database.MagicPlaceholderOptions({})
    for comp_cls, comps in all_comps.items():
      for comp in comps:
        comp_name_replacer = _LineSplitter.GeneratePlaceholderKey(
            f'component-{comp_cls}-{comp.name}')
        comp_status_replacer = _LineSplitter.GeneratePlaceholderKey(
            f'support_status-{comp_cls}-{comp.name}')
        db_placeholder_options.components[(comp_cls, comp.name)] = (
            database.MagicPlaceholderComponentOptions(comp_name_replacer,
                                                      comp_status_replacer))

        all_placeholders[comp_name_replacer] = DBLineAnalysisResult.Part(
            DBLineAnalysisResult.Part.Type.COMPONENT_NAME, comp_name_replacer)
        all_placeholders[comp_status_replacer] = DBLineAnalysisResult.Part(
            DBLineAnalysisResult.Part.Type.COMPONENT_STATUS, comp_name_replacer)

        if (comp.extracted_seq_no is not None and
            comp.extracted_seq_no != str(comp.expected_seq_no)):
          comp_name_with_correct_seq_no = ''.join([
              comp.extracted_noseq_comp_name, name_pattern_adapter.SEQ_SEP,
              str(comp.expected_seq_no)
          ])
        else:
          comp_name_with_correct_seq_no = None
        raw_comp_name = yaml.safe_dump(comp.name).partition('\n')[0]
        report.hwid_components[comp_name_replacer] = (
            HWIDComponentAnalysisResult(
                comp_cls, raw_comp_name, comp.status, comp.is_newly_added,
                comp.extracted_name_info, comp.expected_seq_no,
                comp_name_with_correct_seq_no, comp.null_values, comp.diff_prev,
                comp.link_avl))

    if require_hwid_db_lines:
      if db_contents_patcher is None:
        raise ValueError(('db_contents_patcher should not be None when '
                          'require_hwid_db_lines is set to True'))
      report.lines.extend(
          self._AnalyzeDBLines(db_contents_patcher, all_placeholders,
                               db_placeholder_options))
    return report

  class _HWIDComponentMetadata(NamedTuple):
    name: str
    status: str
    extracted_noseq_comp_name: str
    extracted_seq_no: Optional[str]
    extracted_name_info: Optional[ComponentNameInfo]
    expected_seq_no: int
    is_newly_added: bool
    null_values: bool
    diff_prev: Optional[DiffStatus]
    link_avl: bool

  def _ExtractHWIDComponents(self) -> Dict[str, List['_HWIDComponentMetadata']]:
    ret = {}
    adapter = name_pattern_adapter.NamePatternAdapter()
    for comp_cls in self._curr_db.instance.GetActiveComponentClasses():
      ret[comp_cls] = []
      name_pattern = adapter.GetNamePattern(comp_cls)
      prev_items = (() if
                    (self._prev_db is None or self._prev_db.instance is None)
                    else self._prev_db.instance.GetComponents(comp_cls).items())
      curr_items = self._curr_db.instance.GetComponents(comp_cls).items()

      for expected_seq, (curr_item, prev_item) in enumerate(
          itertools.zip_longest(curr_items, prev_items, fillvalue=None), 1):
        if curr_item is None:
          logging.debug('Remove components (more comps in prev db)')
          break
        comp_name, comp_info = curr_item
        name_info = name_pattern.Matches(comp_name)
        noseq_comp_name, sep, actual_seq = comp_name.partition(
            name_pattern_adapter.SEQ_SEP)
        null_values = comp_info.values is None
        link_avl = isinstance(comp_info.values, rule.AVLProbeValue)

        diffstatus = None
        if prev_item:
          prev_comp_name, prev_comp_info = prev_item
          prev_support_status = prev_comp_info.status
          name_changed = prev_comp_name != comp_name
          support_status_changed = prev_support_status != comp_info.status
          values_changed = prev_comp_info.values != comp_info.values
          unchanged = not (name_changed or support_status_changed or
                           values_changed)
          diffstatus = DiffStatus(unchanged, name_changed,
                                  support_status_changed, values_changed,
                                  prev_comp_name, prev_support_status)
          is_newly_added = False
        else:
          is_newly_added = True

        ret[comp_cls].append(
            self._HWIDComponentMetadata(
                comp_name, comp_info.status, noseq_comp_name,
                actual_seq if sep else None, name_info, expected_seq,
                is_newly_added, null_values, diffstatus, link_avl))
    return ret

  @classmethod
  def _LoadFromDBContents(cls, db_contents: str,
                          expected_checksum: Optional[str]) -> 'DBSnapshot':
    try:
      db = database.Database.LoadData(db_contents,
                                      expected_checksum=expected_checksum)
      load_error = None
    except (schema.SchemaException, common.HWIDException,
            yaml.error.YAMLError) as ex:
      db = None
      load_error = ex
    return cls.DBSnapshot(db_contents, db, load_error)


class _LineSplitter:

  _PLACEHOLDER_KEY_MATCHER = re.compile(r'(x@@@@[^@]+@@y@)')

  @classmethod
  def GeneratePlaceholderKey(cls, placeholder_identity):
    # Prefix "x" prevents yaml from quoting the string.  The "y" in the
    # suffix part prevents the overlapped search result.
    return f'x@@@@{placeholder_identity.replace("@", "<at>")}@@y@'

  def __init__(self, placeholders, text_part_factory):
    self._placeholders = placeholders
    self._text_part_factory = text_part_factory

  def SplitText(self, text):
    parts = []
    curr_pos = re_curr_pos = 0
    while True:
      matched_result = self._PLACEHOLDER_KEY_MATCHER.search(
          text, pos=re_curr_pos)
      if not matched_result:
        break
      placeholder_key = matched_result[0]
      try:
        placeholder_sample = self._placeholders[placeholder_key]
      except KeyError:
        logging.warning(
            'Matched unexpected placeholder string: %s, maybe the '
            'prefix / suffix are not magical enough?', placeholder_key)
        re_curr_pos = matched_result.end()
        continue
      if curr_pos < matched_result.start():
        parts.append(
            self._text_part_factory(text[curr_pos:matched_result.start()]))
      parts.append(copy.deepcopy(placeholder_sample))
      curr_pos = re_curr_pos = matched_result.end()
    if curr_pos < len(text):
      parts.append(self._text_part_factory(text[curr_pos:]))
    return parts
