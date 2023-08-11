# Copyright 2023 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

import logging
import re

from cros.factory.gooftool import vpd_data
from cros.factory.test.rules.privacy import FilterDict
from cros.factory.test.utils import smart_amp_utils
from cros.factory.utils import config_utils
from cros.factory.utils.type_utils import Error

from cros.factory.external.chromeos_cli import cros_config
from cros.factory.external.chromeos_cli import vpd


class VPDError(Error):
  pass


class VPDUtils:

  def __init__(self, project):
    self.project = project
    self._vpd = vpd.VPDTool()
    self._cros_config = cros_config.CrosConfig()

  def _GetInvalidVPDFields(self, data, known_vpd, known_vpd_re):
    """Gets the invalid VPD fields from `data`.

    Invalid VPDs are VPDs with unknown keys or unmatched value pattern.

    Args:
      data: a mapping of (key, value) for VPD data.
      known_vpd: a mapping of (key, format_RE) for known data.
      known_vpd_re: a mapping of (key_re, format_RE) for known data.

    Returns:
      A list of unknown keys and a list of (key, pattern) tuple where the
      value of the key does not match the expected pattern.
    """
    unknown_keys = []
    misformat_key_pattern = []
    for k, v in data.items():
      if k in known_vpd:
        if not re.fullmatch(known_vpd[k], v):
          misformat_key_pattern.append((k, known_vpd[k]))
        continue

      for rk, rv in known_vpd_re.items():
        if re.fullmatch(rk, k):
          if not re.fullmatch(rv, v):
            misformat_key_pattern.append((k, rv))
          break
      else:
        unknown_keys.append(k)

    return unknown_keys, misformat_key_pattern

  def ClearUnknownVPDEntries(self):
    rw_vpd = self._vpd.GetAllData(partition=vpd.VPD_READWRITE_PARTITION_NAME)
    known_rw_vpd = dict(vpd_data.REQUIRED_RW_DATA, **vpd_data.KNOWN_RW_DATA)
    unknown_keys, unused_misformat_key_pattern = self._GetInvalidVPDFields(
        rw_vpd, known_rw_vpd, vpd_data.KNOWN_RW_DATA_RE)
    logging.info('Current RW VPDs: %r', FilterDict(rw_vpd))
    if unknown_keys:
      self._ClearRWVPDEntries(unknown_keys)
    else:
      logging.info('No unknown RW VPDs are found. Skip clearing.')

    return unknown_keys

  def _ClearRWVPDEntries(self, keys):
    logging.info('Removing VPD entries with key %r', keys)
    try:
      self._vpd.UpdateData({k: None
                            for k in keys},
                           partition=vpd.VPD_READWRITE_PARTITION_NAME)
    except Exception as e:
      raise VPDError(f'Failed to remove VPD entries: {e!r}') from None

  def CheckVPDFields(self, section, data, required, optional, optional_re):
    """Checks if all fields in data fall into given format.

    Args:
      section: a string for VPD section name, 'RO' or 'RW.
      data: a mapping of (key, value) for VPD data.
      required: a mapping of (key, format_RE) for required data.
      optional: a mapping of (key, format_RE) for optional data.
      optional_re: a mapping of (key_re, format_RE) for optional data.

    Returns:
      A list of verified keys.

    Raises:
      ValueError if some value does not match format_RE.
      KeyError if some unexpected VPD key name is found.
    """
    known = required.copy()
    known.update(optional)
    unknown_keys, misformat_key_pattern = self._GetInvalidVPDFields(
        data, known, optional_re)

    errors = []
    for k in unknown_keys:
      errors.append(f'Unexpected {section} VPD: {k}={data[k]}.')

    for k, pattern in misformat_key_pattern:
      errors.append(f'Incorrect {section} VPD: {k}={data[k]} '
                    f'(expected format: {pattern})')

    missing_keys = set(required).difference(set(data.keys()))
    if missing_keys:
      errors.append(
          f"Missing required {section} VPD values: {','.join(missing_keys)}")

    if errors:
      raise VPDError('\n'.join(errors))

  def ClearFactoryVPDEntries(self):
    """Clears factory related VPD entries in the RW VPD.

    All VPD entries with '.' in key name are considered as special.
    We collect all special names and delete entries with known prefixes,
    and fail if there are unknown entries left.

    Returns:
      A dict of the removed entries.
    """

    def _IsFactoryVPD(k):
      # These names are defined in cros.factory.test.device_data
      known_names = ['factory.', 'component.', 'serials.']
      return any(name for name in known_names if k.startswith(name))

    rw_vpd = self._vpd.GetAllData(partition=vpd.VPD_READWRITE_PARTITION_NAME)
    dot_entries = {k: v
                   for k, v in rw_vpd.items()
                   if '.' in k}
    logging.info('Current special RW VPDs: %r', FilterDict(dot_entries))
    entries = {k: v
               for k, v in dot_entries.items()
               if _IsFactoryVPD(k)}
    unknown_keys = set(dot_entries) - set(entries)
    if unknown_keys:
      raise VPDError(f'Found unexpected RW VPD(s): {unknown_keys!r}')

    if entries:
      self._ClearRWVPDEntries(entries.keys())
    else:
      logging.info('No factory-related RW VPDs are found. Skip clearing.')

    return entries

  def GetAudioVPDROData(self):
    """Return the required audio VPD RO data.

    If a DUT comes with a smart amplifier, it must be calibrated in the
    factory and the DSM-related VPD values must be set.
    """
    speaker_amp, sound_card_init_file, channel_names = \
      smart_amp_utils.GetSmartAmpInfo()
    if speaker_amp:
      logging.info('Amplifier %s found on DUT.', speaker_amp)
    if not sound_card_init_file:
      logging.info('No smart amplifier found! '
                   'Skip checking DSM VPD value.')
      return {}

    num_channels = len(channel_names)
    logging.info(
        'The VPD RO should contain `dsm_calib_r0_N` and '
        '`dsm_calib_temp_N` where N ranges from 0 ~ %d.', num_channels - 1)
    dsm_vpd_ro_data = {}
    for channel in range(num_channels):
      dsm_vpd_ro_data[f'dsm_calib_r0_{int(channel)}'] = r'[0-9]*'
      dsm_vpd_ro_data[f'dsm_calib_temp_{int(channel)}'] = r'[0-9]*'

    return dsm_vpd_ro_data

  def GetDeviceNameForRegistrationCode(self, project):

    def _LoadConfigJsonFile(_config):
      try:
        return config_utils.LoadConfig(_config, validate_schema=False)
      except Exception:
        return None

    config = 'custom_label_reg_code'
    # Load config json file
    reg_code_config = _LoadConfigJsonFile(config)
    if reg_code_config is None:
      # Fallback to the legacy name.
      reg_code_config = _LoadConfigJsonFile('whitelabel_reg_code')
      if reg_code_config:
        logging.warning(
            '"whitelabel_reg_code.json is deprecated, please rename it to %s',
            config)

    if reg_code_config is None:
      return project

    if project not in reg_code_config:
      return project

    # Get the custom-label-tag for custom label device
    is_custom_label, custom_label_tag = self._cros_config.GetCustomLabelTag()
    if (not is_custom_label or
        custom_label_tag not in reg_code_config[project]):
      return project
    if reg_code_config[project][custom_label_tag]:
      return custom_label_tag
    return project
