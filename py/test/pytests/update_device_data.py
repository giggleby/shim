# Copyright 2017 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.


"""Updates Device Data (manually or from predefined values in test list).

Description
-----------
The Device Data (``cros.factory.test.device_data``) is a special data structure
for manipulating DUT information.  This test can determine Device Data
information (usually for VPD) without using shopfloor backend, usually
including:

- ``serials.serial_number``: The device serial number.
- ``vpd.ro.region``: Region data (RO region).
- ``vpd.rw.ubind_attribute`` and ``vpd.rw.gbind_attribute``: User and group
  registration codes.
- Or other values specified in argument ``fields`` or ``config_name``.

When argument `manual_input` is True, every values specified in ``fields`` will
be displayed on screen with an edit box before written into device data.
Note all the values will be written as string in manual mode.

The ``fields`` argument is a sequence in format
``(data_key, value, display_name, value_check)``:

================ ==============================================================
Name             Description
================ ==============================================================
``data_key``     The Device Data key name to write.
``value``        The value to be written, can be modified if ``manual_input`` is
                 True.
``display_name`` The label or name to be displayed on UI.
``value_check``  To validate the input value. Can be a regular expression,
                 list of strings, list of integers, boolean values, or
                 None.
                 When ``value_check`` is a list of strings / integers / bool, an
                 "option label" can be added to each option.  So ``value_check``
                 becomes a list of tuples: ``[ (string, string) ]`` or ``[ (int,
                 string) ]`` or ``[ (bool, string) ]``.  The first element of
                 tuple is the value, and the second element is a string to be
                 displayed.
================ ==============================================================

If you want to manually configure without default values, the sequence can be
replaced by a simple string of key name.

The ``config_name`` refers to a JSON config file loaded by
``cros.factory.py.utils.config_utils`` with single dictionary that the keys
and values will be directly sent to Device Data. This is helpful if you need to
define board-specific data.

``config_name`` and ``fields`` are both optional, but you must specify at least
one.

If you want to set device data (especially VPD values) using shopfloor or
pre-defined values:

1. Use ``shopfloor_service`` test with method=GetDeviceInfo to retrieve
   ``vpd.{ro,rw}.*``.
2. Use ``update_device_data`` test to write pre-defined or update values to
   ``vpd.{ro,rw}.*``.
3. Use ``write_device_data_to_vpd`` to flush data into firmware VPD sections.

Test Procedure
--------------
If argument ``manual_input`` is not True, this will be an automated test
without user interaction.

If argument ``manual_input`` is True, the test will go through all the fields:

1. Display the name and key of the value.
2. Display an input edit box for simple values, or a list of selection
   if the ``value_check`` is a sequence of strings or boolean values.
3. Wait for operator to select or input right value.
4. If operator presses ESC, abandon changes and keep original value.
5. If operator clicks Enter, validate the input by ``value_check`` argument.
   If failed, prompt and go back to 3.
   Otherwise, write into device data and move to next field.
6. Pass when all fields were processed.

Dependency
----------
None. This test only deals with the ``device_data`` module inside factory
software framework.

Examples
--------
To silently load device-specific data defined in board overlay
``py/config/default_device_data.json``, add this in test list::

  {
    "pytest_name": "update_device_data",
    "args": {
      "config_name": "default",
      "manual_input": false
    }
  }

To silently set a device data 'component.has_touchscreen' to True::

  {
    "pytest_name": "update_device_data",
    "args": {
      "fields": [
        [
          "component.has_touchscreen",
          true,
          "Device has touch screen",
          null
        ]
      ],
      "manual_input": false
    }
  }

For RMA process to set serial number, region, registration codes, and specify
if the device has peripherals like touchscreen::

  {
    "pytest_name": "update_device_data",
    "args": {
      "fields": [
        [
          "serials.serial_number",
          null,
          "Device Serial Number",
          "[A-Z0-9]+"
        ],
        ["vpd.ro.region", "us", "Region", null],
        ["vpd.rw.ubind_attribute", null, "User ECHO", null],
        ["vpd.rw.gbind_attribute", null, "Group ECHO", null],
        [
          "component.has_touchscreen",
          null,
          "Has touchscreen",
          [true, false]
        ]
      ]
    }
  }

If you don't need default values, there's an alternative to list only key
names::

  {
    "pytest_name": "update_device_data",
    "args": {
      "fields": [
        "serials.serial_number",
        "vpd.ro.region",
        "vpd.rw.ubind_attribute",
        "vpd.rw.gbind_attribute"
      ]
    }
  }
"""

import logging
import queue
import re

from cros.factory.test import device_data
from cros.factory.test import i18n
from cros.factory.test.i18n import _
from cros.factory.test.l10n import regions
from cros.factory.test import test_case
from cros.factory.test import test_ui
from cros.factory.test import ui_templates
from cros.factory.utils.arg_utils import Arg
from cros.factory.utils import sync_utils

# Known regions to be listed first.
_COMMONLY_USED_REGIONS = (
    'us',
    'gb',
    'de',
    'fr',
    'ch',
    'nordic',
    'latam-es-419',
)

_KNOWN_KEY_LABELS = {
    device_data.KEY_SERIAL_NUMBER: _('Device Serial Number'),
    device_data.KEY_MLB_SERIAL_NUMBER: _('Mainboard Serial Number'),
    device_data.KEY_VPD_REGION: _('VPD Region Code'),
    device_data.KEY_VPD_USER_REGCODE: _('User Registration Code'),
    device_data.KEY_VPD_GROUP_REGCODE: _('Group Registration Code'),
}

_SELECTION_PER_PAGE = 10

class UpdateDeviceData(test_case.TestCase):
  ARGS = [
      Arg('manual_input', bool,
          'Set to False to silently updating all values. Otherwise each value '
          'will be prompted before set into Device Data.',
          default=True),
      Arg('config_name', str,
          'A JSON config name to load representing the device data to update.',
          default=None),
      Arg('fields', list,
          ('A list of [data_key, value, display_name, value_check] '
           'indicating the Device Data field by data_key must be updated to '
           'specified value.'),
          default=None),
  ]

  def setUp(self):
    # Either config_name or fields must be specified.
    if self.args.config_name is None and self.args.fields is None:
      raise ValueError('Either config_name or fields must be specified.')

    fields = []

    if self.args.config_name:
      fields += [(k, v, None, None) for k, v in
                 device_data.LoadConfig(self.args.config_name).items()]

    if self.args.fields:
      fields += self.args.fields

    # Syntax sugar: If the sequence was replaced by a simple string, consider
    # that as data_key only.
    self.entries = [
        CreateDataEntry(args)
        if isinstance(args, str) else CreateDataEntry(*args) for args in fields
    ]

    # Setup UI and update accordingly.
    self.ui.ToggleTemplateClass('font-large', True)

  def runTest(self):
    if self.args.manual_input:
      for entry in self.entries:
        self.ManualInput(entry)
    else:
      results = {entry.key: entry.value for entry in self.entries}
      device_data.UpdateDeviceData(results)

  def ManualInput(self, entry):
    event_subtype = 'devicedata-' + entry.key
    event_queue = queue.Queue()

    if isinstance(entry, SelectionDataEntry):
      self._RenderSelectBox(entry)
      self.ui.BindKeyJS(test_ui.ENTER_KEY, 'window.sendSelectValue(%r, %r)' %
                        (entry.key, event_subtype))
    else:
      self._RenderInputBox(entry)
      self.ui.BindKey(
          test_ui.ESCAPE_KEY, lambda unused_event: event_queue.put(None))
      self.ui.BindKeyJS(test_ui.ENTER_KEY, 'window.sendInputValue(%r, %r)' % (
          entry.key, event_subtype))

    self.event_loop.AddEventHandler(event_subtype, event_queue.put)

    while True:
      event = sync_utils.QueueGet(event_queue)
      if event is None:
        # ESC pressed.
        if entry.value is not None:
          break
        self._SetErrorMsg(
            _('No valid data on machine for {label}.', label=entry.label))
      else:
        try:
          entry.SetValueFromString(event.data)
          device_data.UpdateDeviceData({entry.key: entry.GetValue()})
          break
        except ValueError:
          self._SetErrorMsg(_('Invalid value for {label}.', label=entry.label))

    self.ui.UnbindAllKeys()
    self.event_loop.ClearHandlers()

  def _SetErrorMsg(self, msg):
    self.ui.SetHTML(
        ['<span class="test-error">', msg, '</span>'], id='errormsg')

  def _RenderSelectBox(self, entry):
    # Renders a select box to list all the possible values.
    select_box = ui_templates.SelectBox(entry.key, _SELECTION_PER_PAGE)
    for value, option in entry.GetOptions():
      select_box.AppendOption(value, option)

    try:
      select_box.SetSelectedIndex(entry.GetSelectedIndex())
    except ValueError:
      pass

    html = [
        _('Select {label}:', label=entry.label),
        select_box.GenerateHTML(),
        _('Select with ENTER')
    ]

    self.ui.SetState(html)
    self.ui.SetFocus(entry.key)

  def _RenderInputBox(self, entry):
    html = [
        _('Enter {label}: ', label=entry.label),
        '<input type="text" id="%s" value="%s" style="width: 20em;">'
        '<div id="errormsg" class="test-error"></div>' % (entry.key,
                                                          entry.value or '')
    ]

    if entry.value:
      # The "ESC" is available primarily for RMA and testing process, when
      # operator does not want to change existing serial number.
      html.append(_('(ESC to keep current value)'))

    self.ui.SetState(html)
    self.ui.SetSelected(entry.key)
    self.ui.SetFocus(entry.key)


class DataEntry:
  """A simple data store for storing DeviceData"""

  def __init__(self, key, value, label):
    self.key = key
    self.value = value
    self.label = label

  def GetValue(self):
    return self.value

  def SetValueFromString(self, value):
    raise NotImplementedError


class TextDataEntry(DataEntry):
  """A data store holding DeviceData as string type field.

  Raises:
    Generic Exception if the pattern_check cannot compile.
  """

  def __init__(self, key, value, label, pattern_check):
    super().__init__(key, value, label)
    self._pattern_check = pattern_check
    self._regex_check = None if pattern_check is None else re.compile(
        pattern_check)

  def SetValueFromString(self, value):
    """Sets the value in data store with validation with string type.

    Raises:
      ValueError if the value does not mat ch regex pattern check.
    """
    if self._regex_check is not None and not self._regex_check.match(value):
      raise ValueError(
          f'Cannot use value {value} for key {self.key}: not matching pattern '
          f'{self._pattern_check}')
    self.value = value


class SelectionDataEntry(DataEntry):
  """A data store holding DeviceData which value can only be in a set.

  Args:
    key: device data key.
    value: default value for device data key.
    options: list of (option_value, option_text) tuples options, where the
      option_value is the dedicated type of the option, and the option_text is a
      pure string.
  """

  def __init__(self, key, value, label, options):
    super().__init__(key, value, label)
    self._option_values = [option[0] for option in options]
    self._option_texts = [option[1] for option in options]

  def SetValueFromString(self, value):
    """Sets the value in data store with validation with string type.

    Args:
      value: string of the option value.

    Raises:
      ValueError if the value is not in options.
    """
    for option_value in self._option_values:
      if str(option_value) == value:
        self.value = option_value
        return
    raise ValueError(
        f'Cannot use value {value} for key {self.key}: not in options')

  def GetOptions(self):
    """Returns valid options.

    Returns:
      A list of tuples corresponding to the HTML select option, i.e. (option
      value, display text), where both display text and option is string, option
      value is the dedicated type of that option.
    """
    return list(zip(self._option_values, self._option_texts))

  def GetSelectedIndex(self):
    """Returns index of current value.

    Returns:
      An integer for the index.

    Raises:
      ValueError if current value is not in options.
    """
    return self._option_values.index(self.value)


def CreateDataEntry(key, value_arg=None, display_name=None,
                    value_check_arg=None):
  """CreateDataEntry is the factory function for creating a DataEntry.

  Args:
    key: a string which is the name of the Device Data key.
    value_arg: a predefined value to use. Should match the field type for the
      key.
    display_name: a string to show when passing to UI component and logs.
    value_check_arg: used to limit the value, can be one of:
      1. None: no limitation.
      2. regex string: value will be validated against this regex check.
      3. an option list: see SelectionDataEntry.

  Returns:
    Either a TextDataEntry or SelectionDataEntry instance.

  Raises:
    ValueError if key is invalid, or invalid arguments for creating different
      kinds of DataEntry.
    TypeError if value_check is invalid.
  """
  # CheckValidDeviceDataKey raises exception if key is invalid.
  device_data.CheckValidDeviceDataKey(key)
  value = value_arg if value_arg is not None else device_data.GetDeviceData(key)
  label = (
      i18n.StringFormat('{name} ({key})', name=GetDisplayNameWithKey(
          key, display_name), key=key))

  if isinstance(value, bool) and value_check_arg is None:
    value_check = [True, False]
  else:
    value_check = value_check_arg

  if key == device_data.KEY_VPD_REGION:
    return SelectionDataEntry(key, value, label,
                              CreateRegionOptions(value_check))
  if isinstance(value_check, list):
    return SelectionDataEntry(key, value, label,
                              CreateSelectOptions(value_check))
  if isinstance(value_check, str) or value_check is None:
    return TextDataEntry(key, value, label, value_check)

  raise TypeError(
      f'value_check ({value_check}) for {key} must be either regex, sequence, '
      'or None.')


def GetDisplayNameWithKey(key, name=None):
  """Gets display name.

  Returns the name if it is given, or use predefined name if key is in
  _KNOWN_KEY_LABELS; otherwise use key as display name.

  Args:
    key: a string which is the name of the Device Data key.
    name: string as display name.

  Returns:
    A string of display name.
  """
  if name is not None:
    return name
  if key in _KNOWN_KEY_LABELS:
    return _KNOWN_KEY_LABELS[key]
  return key


def CreateRegionOptions(allowed_regions=None):
  """Creates region options.

  Args:
    allowed_regions: list of regions. None to use all regions.

  Returns:
    A list of (region_value, region_description) tuples.

  Raises:
    ValueError if any region in allowed_regions is not in all regions.
  """
  all_regions = list(regions.REGIONS)
  if allowed_regions is not None:
    assert isinstance(allowed_regions, list)
    if not set(allowed_regions).issubset(set(all_regions)):
      raise ValueError(
          f'value of options for {device_data.KEY_VPD_REGION} must be a subset '
          'of known regions')
    region_to_use = allowed_regions
  else:
    # Put commonly used regions at the beginning.
    commonly_used_regions = [
        v for v in _COMMONLY_USED_REGIONS if v in all_regions
    ]
    rest_regions = sorted(set(all_regions) - set(commonly_used_regions))
    region_to_use = commonly_used_regions + rest_regions

  region_options = []
  for idx, region in enumerate(region_to_use):
    region_description = regions.REGIONS[region].description
    option_display_text = f'{idx+1} - {region}: {region_description}'
    region_options.append((region, option_display_text))
  return region_options


def CreateSelectOptions(value_check):
  """Creates a list of options.

  Args:
    value_check: list of value_check items, where items can be str, int, bool,
      or list.

  Returns:
    A list of (option_value, option_text) tuples.

  Raises:
    ValueError if item is invalid.
  """
  options = []
  for i, e in enumerate(value_check):
    if isinstance(e, (str, int, bool)):
      options.append((e, f'{i + 1} - {e}'))
    elif isinstance(e, list):
      if len(e) == 0:
        raise ValueError(
            'Each element of `value_check` must not be an empty list')

      if len(e) == 1:
        options.append((e[0], f'{i + 1} - {e[0]}'))
      elif len(e) == 2:
        options.append((e[0], f'{i + 1} - {e[1]}'))
      else:
        logging.warning('Each element of value_check is either a single '
                        'value or a two value tuple. Extra values will be '
                        'truncated.')
        options.append((e[0], f'{i + 1} - {e[1]}'))
    else:
      raise ValueError(f'Unsupported value_check {value_check}')
  return options
