# Copyright 2023 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

import logging
import subprocess

import yaml

from cros.factory.probe import function
from cros.factory.probe.lib import cached_probe_function
from cros.factory.utils import process_utils
from cros.factory.utils import schema


class EmbeddedControllerFunction(cached_probe_function.CachedProbeFunction):
  """Get information of EC.

  Description
  -----------
  This probe function is simply a wrapper of the command ``ectool chipinfo``.

  Examples
  --------
  Assuming the output of ``ectool chipinfo`` is ::

    Chip info:
      vendor:    abc
      name:      def
      revision:  xyz

  Then the probed results of the probe statement
  ``{"eval": "embedded_controller"}`` will be ::

    [
      {
        "vendor": "abc",
        "name": "def"
        "revision": "xyz"
      }
    ]

  """
  _ECTOOL_CHIPINFO_COMMAND = ('ectool', 'chipinfo')
  _ECTOOL_CHIPINFO_SECTION_TITLE = 'Chip info'
  _REQUIRED_FIELD_NAMES = frozenset(('vendor', 'name', 'revision'))
  _ECTOOL_CHIPINFO_SCHEMA = schema.FixedDict(
      'ectool chipinfo output', items={
          _ECTOOL_CHIPINFO_SECTION_TITLE:
              schema.FixedDict(
                  _ECTOOL_CHIPINFO_SECTION_TITLE, items={
                      field_name: schema.Scalar(field_name, str)
                      for field_name in _REQUIRED_FIELD_NAMES
                  }, allow_undefined_keys=True)
      }, allow_undefined_keys=True)

  def GetCategoryFromArgs(self):
    return None

  @classmethod
  def ProbeAllDevices(cls):
    try:
      raw_output = process_utils.CheckOutput(cls._ECTOOL_CHIPINFO_COMMAND)
    except subprocess.CalledProcessError:
      logging.exception('Failed to invoke the subcommand: %r.',
                        cls._ECTOOL_CHIPINFO_COMMAND)
      return function.NOTHING

    try:
      parsed_output = yaml.load(raw_output, Loader=yaml.BaseLoader)
      cls._ECTOOL_CHIPINFO_SCHEMA.Validate(parsed_output)
    except (yaml.YAMLError, schema.SchemaException):
      logging.exception('Failed to parse subcommand output: %r.', raw_output)
      return function.NOTHING

    chipinfo_section = parsed_output[cls._ECTOOL_CHIPINFO_SECTION_TITLE]
    return [{
        field_name: chipinfo_section[field_name]
        for field_name in cls._REQUIRED_FIELD_NAMES
    }]
