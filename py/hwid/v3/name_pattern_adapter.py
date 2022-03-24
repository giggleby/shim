# Copyright 2020 The Chromium OS Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

import io
import re
from typing import Callable, Match, NamedTuple, Optional, TypeVar, Union

SEQ_SEP = '#'  # Separator between the component name and the sequential suffix.


class NameInfo(NamedTuple):
  """A collection of information embedded in a HWID component name.

  Attributes:
    cid: Component ID of the corresponding AVL entry.
    qid: An integer of qualification ID (or 0) of the corresponding AVL entry if
        it is a regular component.  `None` if it's a sub-component.
    is_subcomp: Whether this entry represents a sub-component.
  """
  cid: int
  qid: Optional[int]
  is_subcomp: bool

  @classmethod
  def from_comp(cls, cid: int, qid: int = 0) -> 'NameInfo':
    """Creates an instance that represents a regular component."""
    return cls(cid, qid, is_subcomp=False)

  @classmethod
  def from_subcomp(cls, cid: int) -> 'NameInfo':
    """Creates an instance that represents a sub-component."""
    return cls(cid, None, is_subcomp=True)


_GroupValueType = TypeVar('_GroupValueType')


def _GetTypedMatchGroup(
    match: Match[str], group_id: Union[int, str],
    group_value_converter: Callable[..., _GroupValueType],
    default: Optional[_GroupValueType] = None) -> _GroupValueType:
  """Helps convert the specified regexp matched group to certain value type.

  Args:
    match: The regexp match object that provides groups.
    group_id: The identity of the target group.
    group_value_converter: A callable object with 1 parameter that converts
      the obtained raw group value to the value to return.
    default: If specified, this function returns the specified default value
      when the un-converted group value is `None`.

  Returns:
    The converted group value, or `default`.
  """
  raw_group_value = match.group(group_id)
  if default is not None and raw_group_value is None:
    return default
  return group_value_converter(raw_group_value)


class NamePattern:

  assert len(SEQ_SEP) == 1
  _SUBCOMP_ANNOTATION = 'subcomp'
  _COMP_VALUE_PATTERN = (
      r'_(?P<cid>\d+)(_(?P<qid>\d+))?({sep}[^{sep}]+)?'.format(
          sep=re.escape(SEQ_SEP)))
  _SUBCOMP_VALUE_PATTERN = r'_{annot}_(?P<cid>\d+)({sep}[^{sep}]+)?'.format(
      annot=re.escape(_SUBCOMP_ANNOTATION), sep=re.escape(SEQ_SEP))

  def __init__(self, comp_cls: str):
    self._comp_cls = comp_cls
    comp_cls_in_re = re.escape(comp_cls)
    self._comp_pattern = re.compile(comp_cls_in_re + self._COMP_VALUE_PATTERN)
    self._subcomp_pattern = re.compile(comp_cls_in_re +
                                       self._SUBCOMP_VALUE_PATTERN)

  def Matches(self, tag: str) -> Optional[NameInfo]:
    matched_result = self._comp_pattern.fullmatch(tag)
    if matched_result:
      return NameInfo.from_comp(
          _GetTypedMatchGroup(matched_result, 'cid', int),
          _GetTypedMatchGroup(matched_result, 'qid', int, default=0),
      )

    matched_result = self._subcomp_pattern.fullmatch(tag)
    if matched_result:
      return NameInfo.from_subcomp(
          _GetTypedMatchGroup(matched_result, 'cid', int))

    return None

  def GenerateAVLName(self, name_info: NameInfo, seq: Optional[str] = None):
    name_buf = io.StringIO()
    name_buf.write(self._comp_cls)
    if name_info.is_subcomp:
      name_buf.write('_')
      name_buf.write(self._SUBCOMP_ANNOTATION)
    name_buf.write('_')
    name_buf.write(str(name_info.cid))
    if name_info.qid:
      name_buf.write('_')
      name_buf.write(str(name_info.qid))
    if seq:
      name_buf.write(SEQ_SEP)
      name_buf.write(seq)
    return name_buf.getvalue()


class NamePatternAdapter:

  def GetNamePattern(self, comp_cls):
    return NamePattern(comp_cls)
