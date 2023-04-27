# Copyright 2023 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

from typing import Mapping, Sequence, Union

from cros.factory.probe_info_service.app_engine import stubby_pb2  # pylint: disable=no-name-in-module


def ProbeInfoFromMapping(
    mapping: Mapping[str, Union[str, int, Sequence[Union[str, int]]]]):
  probe_parameters = []
  for name, value_or_values in mapping.items():
    values = value_or_values if isinstance(value_or_values,
                                           list) else [value_or_values]
    for value in values:
      kwargs = {
          'name': name
      }
      kwargs['string_value' if isinstance(value, str) else 'int_value'] = value
      probe_parameters.append(stubby_pb2.ProbeParameter(**kwargs))
  return stubby_pb2.ProbeInfo(probe_parameters=probe_parameters)
