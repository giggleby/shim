# Copyright 2023 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

from __future__ import annotations

import abc
from typing import Generic, NamedTuple, Optional, Sequence, TypeVar

from cros.factory.probe_info_service.app_engine import stubby_pb2  # pylint: disable=no-name-in-module


ProbeSchema = stubby_pb2.ProbeSchema
ProbeFunctionDefinition = stubby_pb2.ProbeFunctionDefinition
ProbeParameterDefinition = stubby_pb2.ProbeParameterDefinition
ProbeParameterValueType = stubby_pb2.ProbeParameterDefinition.ValueType

ProbeInfo = stubby_pb2.ProbeInfo
ProbeParameter = stubby_pb2.ProbeParameter

ProbeInfoParsedResult = stubby_pb2.ProbeInfoParsedResult
ProbeParameterSuggestion = stubby_pb2.ProbeParameterSuggestion
ProbeInfoTestResult = stubby_pb2.ProbeInfoTestResult


class PayloadInvalidError(Exception):
  """Exception class raised when the given payload is invalid."""


class IProbeDataSource(abc.ABC):
  """Base type of classes for a source of probe statement and its metadata."""


_T = TypeVar('_T')


class ProbeInfoArtifact(NamedTuple, Generic[_T]):
  """A placeholder for any artifact generated from one single probe info.

  Many tasks performed by this module involve parsing the given `ProbeInfo`
  instance to get any kind of output.  The probe info might not necessary be
  valid, the module need to return a structured summary for the parsed result
  all the time.  This class provides a placeholder for those methods.

  Properties:
    probe_info_parsed_result: An instance of `ProbeInfoParsedResult`.
    output: `None` or any kind of the output.
  """
  probe_info_parsed_result: ProbeInfoParsedResult
  output: Optional[_T]


class MultiProbeInfoArtifact(NamedTuple, Generic[_T]):
  """A placeholder for any artifact generated from multiple probe infos.

  Many tasks performed by this module involve parsing the given `ProbeInfo`
  instances to get any kind of output.  The probe info might not necessary be
  valid, the module need to return a structured summary for the parsed result
  all the time.  This class provides a placeholder for those methods.

  Properties:
    probe_info_parsed_results: A list of instances of `ProbeInfoParsedResult`
    corresponds to the source of array of `ProbeInfo` instances.
    output: `None` or any kind of the output.
  """
  probe_info_parsed_results: Sequence[ProbeInfoParsedResult]
  output: Optional[_T]


class NamedFile(NamedTuple):
  """A placeholder represents a named file."""
  name: str
  content: bytes


class DeviceProbeResultAnalyzedResult(NamedTuple):
  """Placeholder for the analyzed result of a device probe result."""
  intrivial_error_msg: Optional[str]
  probe_info_test_results: Optional[Sequence[ProbeInfoTestResult]]


class IProbeInfoAnalyzer(abc.ABC):
  """Interface of the class that can test and analyze the given probe infos."""

  @abc.abstractmethod
  def GetProbeSchema(self) -> ProbeSchema:
    """Returns the probe schema of all supported probe infos."""

  @abc.abstractmethod
  def ValidateProbeInfo(self, probe_info: ProbeInfo,
                        allow_missing_params: bool) -> ProbeInfoParsedResult:
    """Validate the given probe info.

    Args:
      probe_info: An instance of `ProbeInfo` to be validated.
      allow_missing_params: Whether missing some probe parameters is allowed
          or not.

    Returns:
      The `ProbeInfo` instance with probe parameter value formats being
      standardized.
    """

  @abc.abstractmethod
  def CreateProbeDataSource(self, component_name: str,
                            probe_info: ProbeInfo) -> IProbeDataSource:
    """Creates the probe data source from the given probe_info."""

  @abc.abstractmethod
  def DumpProbeDataSource(
      self, probe_data_source: IProbeDataSource) -> ProbeInfoArtifact[str]:
    """Dump the probe data source to a loadable probe statement string."""

  @abc.abstractmethod
  def GenerateDummyProbeStatement(
      self, reference_probe_data_source: IProbeDataSource) -> str:
    """Generate a dummy loadable probe statement string.

    This is a backup-plan in case `DumpProbeDataSource` fails.
    """

  @abc.abstractmethod
  def GenerateRawProbeStatement(
      self, probe_data_source: IProbeDataSource) -> ProbeInfoArtifact[str]:
    """Generate raw probe statement string for the given probe data source.

    Args:
      probe_data_source: The source for the probe statement.

    Returns:
      An instance of `ProbeInfoArtifact`, which `output` property is a string
      of the probe statement or `None` if failed.
    """

  @abc.abstractmethod
  def LoadProbeInfo(self, probe_statement: str) -> ProbeInfo:
    """Loads the given probe statement back to a probe info instance."""

  @abc.abstractmethod
  def GenerateProbeBundlePayload(
      self, probe_data_sources: Sequence[IProbeDataSource]
  ) -> MultiProbeInfoArtifact[NamedFile]:
    """Generates the payload for testing the given probe infos.

    Args:
      probe_data_source: The source of the test bundle.

    Returns:
      An instance of `MultiProbeInfoArtifact`, which `output` property is an
      instance of `NamedFile`, which represents the result payload for the user
      to download.
    """

  @abc.abstractmethod
  def AnalyzeQualProbeTestResultPayload(
      self, probe_data_source: IProbeDataSource,
      probe_result_payload: bytes) -> ProbeInfoTestResult:
    """Analyzes the given probe result payload for a qualification.

    Args:
      probe_data_source: The original source for the probe statement.
      probe_result_payload: A byte string of the payload to be analyzed.

    Returns:
      An instance of `ProbeInfoTestResult`.

    Raises:
      `PayloadInvalidError` if the given input is invalid.
    """

  @abc.abstractmethod
  def AnalyzeDeviceProbeResultPayload(
      self, probe_data_sources: Sequence[IProbeDataSource],
      probe_result_payload: bytes) -> DeviceProbeResultAnalyzedResult:
    """Analyzes the given probe result payload from a specific device.

    Args:
      probe_data_sources: The original sources for the probe statements.
      probed_result_payload: A byte string of the payload to be analyzed.

    Returns:
      List of `ProbeInfoTestResult` for each probe data sources.

    Raises:
      `PayloadInvalidError` if the given input is invalid.
    """
