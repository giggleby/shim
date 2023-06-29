# Copyright 2020 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

import abc
import io
import re
from typing import Callable, Generic, Match, NamedTuple, Optional, TypeVar, Union

from cros.factory.utils import json_utils


SEQ_SEP = '#'  # Separator between the component name and the sequential suffix.
_COMP_SEQ_SUFFIX_PATTERN = re.compile(f'{re.escape(SEQ_SEP)}'
                                      r'\d+$')


def TrimSequenceSuffix(comp_name: str) -> str:
  return _COMP_SEQ_SUFFIX_PATTERN.sub('', comp_name)


def AddSequenceSuffix(comp_name: str, seq: int) -> str:
  return f'{comp_name}{SEQ_SEP}{seq}'


_T = TypeVar('_T')


class NameInfoAcceptor(abc.ABC, Generic[_T]):
  """An acceptor to handle known cases of name info."""

  @abc.abstractmethod
  def AcceptRegularComp(self, cid: int, qid: Optional[int]) -> _T:
    """Accepts regular component with a CID and an optional QID."""

  @abc.abstractmethod
  def AcceptSubcomp(self, cid: int) -> _T:
    """Accepts a sub-component with its corresponding CID."""

  @abc.abstractmethod
  def AcceptLegacy(self, raw_comp_name: str) -> _T:
    """Accepts the legacy component name without following any name policy."""


class NameInfoRawData(NamedTuple):
  cid: Optional[int]
  qid: Optional[int]
  is_subcomp: bool
  legacy_comp_name: Optional[str]


class _NameInfoRawDataAcceptor(NameInfoAcceptor[NameInfoRawData]):
  """An acceptor to provide the raw name info."""

  def AcceptRegularComp(self, cid: int, qid: Optional[int]) -> NameInfoRawData:
    """See base class."""
    return NameInfoRawData(cid, qid, False, None)

  def AcceptSubcomp(self, cid: int) -> NameInfoRawData:
    """See base class."""
    return NameInfoRawData(cid, None, True, None)

  def AcceptLegacy(self, raw_comp_name: str) -> NameInfoRawData:
    """See base class."""
    return NameInfoRawData(None, None, False, raw_comp_name)


class GetCIDAcceptor(NameInfoAcceptor[Optional[int]]):
  """An acceptor to provide CID info."""

  def AcceptRegularComp(self, cid: int, qid: Optional[int]) -> Optional[int]:
    """See base class."""
    del qid
    return cid

  def AcceptSubcomp(self, cid: int) -> Optional[int]:
    """See base class."""
    return cid

  def AcceptUntracked(self) -> Optional[int]:
    """See base class."""
    return None

  def AcceptLegacy(self, raw_comp_name: str) -> Optional[int]:  # pylint: disable=useless-return
    """See base class."""
    del raw_comp_name
    return None


class NameInfoProvider(abc.ABC):
  """The base provider of name info."""

  @abc.abstractmethod
  def Provide(self, acceptor: NameInfoAcceptor[_T]) -> _T:
    """Provides the value per different cases by the acceptor."""

  def __eq__(self, rhs):
    if not isinstance(rhs, NameInfoProvider):
      return False

    return self.Provide(_NAME_INFO_RAW_DATA_ACCEPTOR) == rhs.Provide(
        _NAME_INFO_RAW_DATA_ACCEPTOR)


class LinkAVLNameRegularInfo(NameInfoProvider):
  """A name info of regular component with a CID and an optional QID."""

  def __init__(self, cid: int, qid: Optional[int] = None):
    self._cid = cid
    self._qid = qid

  def Provide(self, acceptor: NameInfoAcceptor[_T]) -> _T:
    """See base class."""
    return acceptor.AcceptRegularComp(self._cid, self._qid)


class LinkAVLNameSubcompInfo(NameInfoProvider):
  """A name info of a sub-component with its corresponding CID."""

  def __init__(self, cid: int):
    self._cid = cid

  def Provide(self, acceptor: NameInfoAcceptor[_T]) -> _T:
    """See base class."""
    return acceptor.AcceptSubcomp(self._cid)


class LegacyNameInfo(NameInfoProvider):
  """A name info of a component without following any name policy."""

  def __init__(self, raw_comp_name: str):
    self._raw_comp_name = raw_comp_name

  def Provide(self, acceptor: NameInfoAcceptor[_T]) -> _T:
    """See base class."""
    return acceptor.AcceptLegacy(self._raw_comp_name)


NameInfo = NameInfoProvider


_GroupValueType = TypeVar('_GroupValueType')


def _GetTypedMatchGroup(
    match: Match[str], group_id: Union[int, str],
    group_value_converter: Callable[..., _GroupValueType],
    default: Optional[_GroupValueType] = None) -> Optional[_GroupValueType]:
  """Helps convert the specified regexp matched group to certain value type.

  Args:
    match: The regexp match object that provides groups.
    group_id: The identity of the target group.
    group_value_converter: A callable object with 1 parameter that converts
      the obtained raw group value to the value to return.
    default: This function returns the specified default value when the
      un-converted group value is `None`.

  Returns:
    The converted group value, or `default`.
  """
  raw_group_value = match.group(group_id)
  if raw_group_value is None:
    return default
  return group_value_converter(raw_group_value)


_NAME_INFO_RAW_DATA_ACCEPTOR = _NameInfoRawDataAcceptor()


def ConvertNameInfoToDict(input_value) -> json_utils.TypeConversionResult:
  """Converts the name info to dict for dumping."""

  if isinstance(input_value, NameInfo):
    return json_utils.TypeConversionResult.from_converted_value(
        input_value.Provide(_NAME_INFO_RAW_DATA_ACCEPTOR)._asdict())

  return json_utils.TypeConversionResult.from_type_not_convered()


class GenerateNameAcceptor(NameInfoAcceptor[str]):
  """An acceptor to generate the component name by its name info."""

  def __init__(self, comp_cls: str):
    self._comp_cls = comp_cls

  def AcceptRegularComp(self, cid: int, qid: Optional[int]) -> str:
    """See base class."""
    if qid is not None:
      return f'{self._comp_cls}_{cid}_{qid}'
    return f'{self._comp_cls}_{cid}'

  def AcceptLegacy(self, raw_comp_name: str) -> str:
    """See base class."""
    return raw_comp_name

  def AcceptSubcomp(self, cid: int) -> str:
    """See base class."""
    return f'{self._comp_cls}_{NamePattern.SUBCOMP_ANNOTATION}_{cid}'


class NamePattern:

  assert len(SEQ_SEP) == 1
  SUBCOMP_ANNOTATION = 'subcomp'
  sep = re.escape(SEQ_SEP)
  _COMP_VALUE_PATTERN = r'_(?P<cid>\d+)(_(?P<qid>\d+))?' f'({sep}\\d+)?'
  annot = re.escape(SUBCOMP_ANNOTATION)
  _SUBCOMP_VALUE_PATTERN = (r'_'
                            f'{annot}'
                            r'_(?P<cid>\d+)'
                            f'({sep}\\d+)?')
  def __init__(self, comp_cls: str):
    self._comp_cls = comp_cls
    comp_cls_in_re = re.escape(comp_cls)
    self._comp_pattern = re.compile(
        f'{comp_cls_in_re}{self._COMP_VALUE_PATTERN}')
    self._subcomp_pattern = re.compile(
        f'{comp_cls_in_re}{self._SUBCOMP_VALUE_PATTERN}')
    self._gen_avl_name_acceptor = GenerateNameAcceptor(self._comp_cls)

  def Matches(self, tag: str) -> NameInfo:
    matched_result = self._comp_pattern.fullmatch(tag)
    if matched_result:
      return LinkAVLNameRegularInfo(
          _GetTypedMatchGroup(matched_result, 'cid', int),
          _GetTypedMatchGroup(matched_result, 'qid', int),
      )

    matched_result = self._subcomp_pattern.fullmatch(tag)
    if matched_result:
      return LinkAVLNameSubcompInfo(
          _GetTypedMatchGroup(matched_result, 'cid', int),
      )

    return LegacyNameInfo(TrimSequenceSuffix(tag))

  def GenerateAVLName(self, name_info: NameInfo, seq: Optional[int] = None):
    name_buf = io.StringIO()
    name_buf.write(name_info.Provide(self._gen_avl_name_acceptor))
    if seq is not None:
      name_buf.write(SEQ_SEP)
      name_buf.write(str(seq))
    return name_buf.getvalue()


class NamePatternAdapter:

  def GetNamePattern(self, comp_cls):
    return NamePattern(comp_cls)
