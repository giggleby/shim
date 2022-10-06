# Copyright 2022 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

import logging

from cros.factory.probe import function
from cros.factory.probe.lib import cached_probe_function
from cros.factory.test import device_data
from cros.factory.utils.arg_utils import Arg


class FactoryDeviceDataFunction(cached_probe_function.CachedProbeFunction):
  """Reads some fields from the device data.

  Description
  -----------
  This probe function is essentially an adapter for the probe-tool user to
  access the factory device data.  It loads the data via the
  ``cros.factory.test.device_data`` module and outputs the specified fields
  as the probed results.

  Examples
  --------

  The following probe statement probes the serial numbers from the device::

    {
      "serial_number": {
        "from_device_data": {
          "eval": {
            "factory_device_data": {
              "device_data_keys": [
                "serials.serial_number",
                "serials.mlb_serial_number"
              ],
              "probed_result_keys": [
                "device_sn",
                "mlb_sn"
              ]
            }
          }
        }
      }
    }

  The statement instructs the probe framework to load ``serials.serial_number``
  and ``serials.mlb_serial_number`` and output them as the value of the fields
  ``device_sn`` and ``mlb_sn`` correspondingly.  Therefore, assume the device
  data contains the following fields::

    serials.serial_number: "aabbcc"
    serials.mlb_serial_number: "ddeeff"

  Then the corresponding output will be::

    {
      "serial_number": [
        {
          "name": "from_device_data",
          "values": {
            "device_sn": "aabbcc",
            "mlb_sn": "ddeeff"
          }
        }
      ],
    }
  """

  ARGS = [
      Arg('device_data_keys', list,
          'A list of the field names of the device data field probe.'),
      Arg(
          'probed_result_keys', list,
          'A list of output field names corresponding to each probed device '
          'data field.  Each element can be either a string of the new field '
          'name or ``None`` to use the original field name.  Leaving this '
          'argument empty is a syntax-sugar for ``[None, None, ...]``.',
          default=None),
  ]

  def __init__(self, **kwargs):
    super().__init__(**kwargs)

    num_fields = len(self.args.device_data_keys)
    if num_fields == 0:
      raise ValueError('At least one device data field should be specified.')
    if self.args.probed_result_keys is None:
      self.args.probed_result_keys = self.args.device_data_keys
    else:
      if len(self.args.probed_result_keys) != num_fields:
        raise ValueError(
            'Length of probed_result_keys and device_data_keys mismatch.')
      for i, probe_result_key in enumerate(self.args.probed_result_keys):
        if probe_result_key is None:
          self.args.probed_result_keys[i] = self.args.device_data_keys[i]

    unique_probe_result_keys = set(self.args.probed_result_keys)
    if len(unique_probe_result_keys) != num_fields:
      raise ValueError('Got duplicated probe result keys.')

  def Probe(self):
    all_device_data_list = super().Probe()
    if not all_device_data_list:
      return function.NOTHING

    # The length of `all_device_data_list` is either 0 or 1.
    all_device_data = all_device_data_list[0]

    probed_results = {}
    for device_data_key, probed_result_key in zip(self.args.device_data_keys,
                                                  self.args.probed_result_keys):
      if device_data_key not in all_device_data:
        logging.error('The device data of key=%r not found.', device_data_key)
        return function.NOTHING
      probed_results[probed_result_key] = all_device_data[device_data_key]
    return [probed_results]

  def GetCategoryFromArgs(self):
    return None

  @classmethod
  def ProbeAllDevices(cls):
    return [device_data.FlattenData(device_data.GetAllDeviceData())]
