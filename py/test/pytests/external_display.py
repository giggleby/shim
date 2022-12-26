# Copyright 2014 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Test external display with optional audio playback test.

Description
-----------
Verify the external display is functional.

The test is defined by a list ``[display_label, display_id,
audio_info, usbpd_spec]``. Each item represents an external port:

- ``display_label``: I18n display name seen by operator, e.g. ``_('VGA')``.
- ``display_id``: (str) ID used to identify display in xrandr or modeprint,
  e.g. VGA1.
- ``audio_info``: A list of ``[audio_card, audio_device, init_actions]``,
  or None:

  - ``audio_card`` is either the card's name (str), or the card's index (int).
  - ``audio_device`` is the device's index (int).
  - ``init_actions`` is a list of ``[card_name, action]`` (list).
    action is a dict key defined in audio.json (ref: audio.py) to be passed
    into dut.audio.ApplyAudioConfig.

  e.g. ``[["rt5650", "init_audio"], ["rt5650", "enable_hdmi"]]``.
  This argument is optional. If set, the audio playback test is added.
- ``usbpd_spec``: An object of cros.factory.device.usb_c.USB_PD_SPEC_SCHEMA, or
  None.

It can also be configured to run automatically by specifying ``bft_fixture``
argument, and skip some steps by setting ``connect_only``,
``start_output_only`` and ``stop_output_only``.

Test Procedure
--------------
This test can be manual or automated depends on whether ``bft_fixture``
is specified. The test loops through all items in ``display_info`` and:

1. Plug an external monitor to the port specified in dargs.
2. (Optional) If ``usbpd_spec`` is specified, verify usbpd status automatically.
3. Main display will automatically switch to the external one.
4. Press the number or HW buttons shown on the display to verify display works.
5. (Optional) If ``audio_info`` is specified, the speaker will play a random
   number, and operator has to press the number to verify audio functionality.
6. Unplug the external monitor to finish the test.

Dependency
----------
- ``display`` component in device API.
- Optional ``audio`` and ``usb_c`` components in device API.
- Optional fixture can be used to support automated test.

Examples
--------
To manual checking external display, add this in test list::

  {
    "pytest_name": "external_display",
    "args": {
      "display_info": [
        {
          "display_label": "i18n! Left HDMI External Display",
          "display_id": "HDMI-A-1"
        }
      ]
    }
  }

To manual checking external display at USB Port 0 with CC1 or CC2, add this in
test list::

  {
    "pytest_name": "external_display",
    "args": {
      "display_info": [
        {
          "display_label": "TypeCLeft USB3 External Display",
          "display_id": "DP-1",
          "usbpd_spec": 0
        }
      ]
    }
  }

To manual checking external display at USB Port 0 CC1, add this in test list::

  {
    "pytest_name": "external_display",
    "args": {
      "display_info": [
        {
          "display_label": "TypeCLeft USB3 CC1 External Display",
          "display_id": "DP-1",
          "usbpd_spec": {
            "port": 0,
            "polarity": 1
          }
        }
      ]
    }
  }

For tablet or Chromebox, use HW buttons instead of keyboard numbers::

  {
    "args": {
      "hw_buttons": [
        ["KEY_VOLUMEDOWN", "Volume Down"],
        ["KEY_VOLUMEUP", "Volume Up"],
        ["KEY_POWER", "Power Button"]
      ],
      "device_filter": "cros_ec_buttons"
    }
  }
"""

import collections
import logging
import os
import queue
import random
from typing import Any, Dict, List, Optional

from cros.factory.device import device_types
from cros.factory.device import device_utils
from cros.factory.device import usb_c
from cros.factory.goofy.plugins import display_manager
from cros.factory.goofy.plugins import plugin_controller
from cros.factory.probe.functions import edid
from cros.factory.test.fixture import bft_fixture
from cros.factory.test.i18n import _
from cros.factory.test.pytests import audio
from cros.factory.test import test_case
from cros.factory.test.utils import button_utils
from cros.factory.utils.arg_utils import Arg
from cros.factory.utils import schema
from cros.factory.utils import sync_utils


# Interval (seconds) of probing connection state.
_CONNECTION_CHECK_PERIOD_SECS = 1
_DEFAULT_DRM_GLOB_PATH = '/sys/class/drm/card?'


ExtDisplayTaskArg = collections.namedtuple('ExtDisplayTaskArg', [
    'display_label', 'display_id', 'audio_card', 'audio_device', 'init_actions',
    'usbpd_spec'
])
_AUDIO_INFO_SCHEMA = schema.JSONSchemaDict(
    'audio_info schema', {
        'type': 'array',
        'items': [
            {
                'type': ['string', 'integer']
            },
            {
                'type': 'integer'
            },
            {
                'type': 'array',
                'items': {
                    'type': 'array',
                    'minItems': 2,
                    'maxItems': 2
                }
            },
        ],
        'minItems': 3,
        'maxItems': 3
    })
_DISPLAY_INFO_SCHEMA_V1 = schema.JSONSchemaDict(
    'display_info schema v1', {
        'type': 'array',
        'items': [
            {
                'type': ['object', 'string']
            },
            {
                'type': 'string'
            },
            _AUDIO_INFO_SCHEMA.CreateOptional().schema,
            usb_c.USB_PD_SPEC_SCHEMA.schema,
        ],
        'minItems': 2,
        'maxItems': 4
    })
_DISPLAY_INFO_SCHEMA_V2 = schema.JSONSchemaDict(
    'display_info schema v2', {
        'type': 'object',
        'properties': {
            'display_label': {
                'type': ['object', 'string']
            },
            'display_id': {
                'type': 'string'
            },
            'audio_info': _AUDIO_INFO_SCHEMA.schema,
            'usbpd_spec': usb_c.USB_PD_SPEC_SCHEMA.schema
        },
        'additionalProperties': False,
        'required': ['display_label', 'display_id']
    })
_DISPLAY_INFO_SCHEMA = schema.JSONSchemaDict('display_info schema', {
    'anyOf': [
        _DISPLAY_INFO_SCHEMA_V1.schema,
        _DISPLAY_INFO_SCHEMA_V2.schema,
    ]
})
_DISPLAY_INFO_LIST_SCHEMA = schema.JSONSchemaDict('display_info list schema', {
    'type': 'array',
    'items': _DISPLAY_INFO_SCHEMA.schema
})


def _MigrateDisplayInfo(display_info):
  if isinstance(display_info, list):
    output = {
        'display_label': display_info[0],
        'display_id': display_info[1]
    }
    if len(display_info) >= 3 and display_info[2]:
      output['audio_info'] = display_info[2]
    if len(display_info) == 4:
      output['usbpd_spec'] = display_info[3]
    return output
  return display_info


class SysfsDisplayInfo:
  """The display info under /sys/class/drm/cardX-YYY."""

  def __init__(self, dut: device_types.DeviceBoard, sysfs_path: str):
    self.sysfs_path = sysfs_path
    self.status_path = dut.path.join(sysfs_path, 'status')
    self.edid_path = dut.path.join(sysfs_path, 'edid')
    self.status = dut.ReadFile(self.status_path).strip()
    self.edid = None
    if self.status != 'connected':
      return
    try:
      edid_data = edid.LoadFromFile(self.edid_path)
      edid_data['manufacturerId'] = edid_data['vendor']
      edid_data['productId'] = edid_data['product_id'].upper()
      edid_data.pop('vendor')
      edid_data.pop('product_id')
      self.edid = edid_data
    except Exception as err:
      raise RuntimeError('No edid or bad edid found from drm_sysfs_path: '
                         f'{sysfs_path}') from err

  def JoinTargetInfo(self, display_info: List[Dict[str, Any]]):
    """Joins target display info between sysfs and Chrome API.

    The Chrome API doesn't tell us which port is using which display so we have
    to use sysfs to find if the target port is connected.

    However, the Chrome API reacts slower than the sysfs and there is a time
    that sysfs thinks the port is connected and the Chrome API thinks it's not.

    If we enter VerifyDisplayConfig before the sysfs and Chrome API sync, the
    VerifyDisplayConfig may fail or return unexpected current and target.

    Args:
      display_info: A List of display info obtained from Chrome API.

    Returns:
      One display info obtained from Chrome API which matched the target edid or
      None if there is no match.
    """
    if self.status != 'connected':
      return None
    for info in display_info:
      for key in ('manufacturerId', 'productId'):
        if info['edid'][key] != self.edid[key]:
          break
      else:
        return info
    return None

class ExtDisplayTest(test_case.TestCase):
  """Main class for external display test."""
  ARGS = [
      Arg('main_display', str,
          "xrandr/modeprint ID for ChromeBook's main display."),
      Arg('display_info', list,
          ('A list of tuples (display_label, display_id, audio_info, '
           'usbpd_spec) represents an external port to test.'),
          schema=_DISPLAY_INFO_LIST_SCHEMA),
      Arg('bft_fixture', dict, bft_fixture.TEST_ARG_HELP, default=None),
      Arg('connect_only', bool,
          ('Just detect ext display connection. This is for a hack that DUT '
           'needs reboot after connect to prevent X crash.'), default=False),
      Arg('start_output_only', bool,
          ('Only start output of external display. This is for bringing up the '
           'external display for other tests that need it.'), default=False),
      Arg('stop_output_only', bool,
          ('Only stop output of external display. This is for bringing down '
           'the external display that other tests have finished using.'),
          default=False),
      Arg('already_connect', bool,
          ('Also for the reboot hack with fixture. With it set to True, DUT '
           'does not issue plug ext display command.'), default=False),
      Arg('drm_sysfs_path', str,
          ('Path of drm sysfs entry. When given this arg, the pytest will '
           'directly get connection status from sysfs path rather than calling '
           'drm_utils. This is needed when the port is running under MST and '
           'thus the display id is dynamic generated.'),
          default=_DEFAULT_DRM_GLOB_PATH),
      Arg(
          'timeout_secs', int,
          'Timeout in seconds when we ask operator to complete the challenge. '
          'None means no timeout.', default=30),
      Arg('hw_buttons', list,
          ('A list of [button_key_name, button_name] represents a HW button to '
           'use. You can refer to HWButton test if you need the params.'),
          default=None),
      Arg('device_filter', (int, str),
          'Event ID or name for evdev. None for auto probe.', default=None),
  ]

  def setUp(self):
    self._dut = device_utils.CreateDUTInterface()
    self._display_manager: Optional[display_manager.DisplayManager] = (
        plugin_controller.GetPluginRPCProxy('display_manager'))
    if not self._display_manager:
      raise RuntimeError('display_manager plugin is not defined.')

    self._fixture = None
    if self.args.bft_fixture:
      self._fixture = bft_fixture.CreateBFTFixture(**self.args.bft_fixture)

    self.buttons = []
    if self.args.hw_buttons:
      for btn in self.args.hw_buttons:
        self.buttons.append((button_utils.Button(
            self._dut, btn[0], self.args.device_filter), btn[1]))
      random.shuffle(self.buttons)

    self.assertLessEqual(
        [self.args.start_output_only, self.args.connect_only,
         self.args.stop_output_only].count(True),
        1,
        'Only one of start_output_only, connect_only '
        'and stop_output_only can be true.')

    self.do_connect, self.do_output, self.do_disconnect = False, False, False

    if self.args.start_output_only:
      self.do_connect = True
      self.do_output = True
    elif self.args.connect_only:
      self.do_connect = True
    elif self.args.stop_output_only:
      self.do_disconnect = True
    else:
      self.do_connect = True
      self.do_output = True
      self.do_disconnect = True

    if self.do_output:
      self.assertTrue(self.do_connect,
                      'If do_output is True then do_connect must be True')

    self._target_display_info = None

    # Setup tasks
    for info in self.args.display_info:
      args = self.ParseDisplayInfo(info)

      self.AddTask(self.Reset)

      if self.do_connect:
        self.AddTask(self.WaitConnect, args)

      if self.do_output:
        self.AddTask(self.CheckVideo, args)
        if args.audio_card:
          self.AddTask(self.SetupAudio, args)
          audio_label = _(
              '{display_label} Audio', display_label=args.display_label)
          self.AddTask(
              audio.TestAudioDigitPlayback, self.ui, self._dut, audio_label,
              card=args.audio_card, device=args.audio_device)

      if self.do_disconnect:
        self.AddTask(self.WaitDisconnect, args)

  def Reset(self):
    """Resets status between different displays."""
    self._target_display_info = None

  def ParseDisplayInfo(self, info):
    """Parses lists from args.display_info.

    Args:
      info: a list in args.display_info. Refer display_info definition.

    Returns:
      Parsed ExtDisplayTaskArg.

    Raises:
      ValueError if parse error.
    """
    info = _MigrateDisplayInfo(info)
    audio_card, audio_device, init_actions = None, None, None
    if 'audio_info' in info:
      audio_info = info['audio_info']
      audio_card = self._dut.audio.GetCardIndexByName(audio_info[0])
      audio_device = audio_info[1]
      init_actions = audio_info[2]

    usbpd_spec = None
    if 'usbpd_spec' in info:
      usbpd_spec = usb_c.MigrateUSBPDSpec(info['usbpd_spec'])

    return ExtDisplayTaskArg(display_label=info['display_label'],
                             display_id=info['display_id'],
                             audio_card=audio_card, audio_device=audio_device,
                             init_actions=init_actions, usbpd_spec=usbpd_spec)

  def CheckVideo(self, args):
    self.ui.BindStandardFailKeys()
    original, target = self.VerifyDisplayConfig()
    logging.info('original=%r, target=%r', original, target)
    # We need to check ``target != original`` because when we test MST ports on
    # a Chromebox device (i.e., no built-in display), `target` and `original`
    # will be the same.  In this situation, we might get the display info from
    # drm sysfs path before the Chrome browser noticing the new external
    # monitor, and thus fail to set the main display.
    if target != original:
      self.SetMainDisplay(target)
    try:
      if self._fixture:
        self.CheckVideoFixture(args)
      else:
        self.CheckVideoManual(args)
    finally:
      if target != original:
        self.SetMainDisplay(original)

  def CheckVideoManual(self, args):
    if self.buttons:
      # Already randomly shuffled while parsing the hw_buttons arguments.
      pass_button = self.buttons[0]

      pass_input = _(pass_button[1])
      # TODO(treapking): Fail the test if wrong HW button is pressed.
      pass_event = lambda: (
          pass_button[0].IsPressed() or not self._IsDisplayConnected(args))
    else:
      key_pressed = queue.Queue()
      keys = [str(i) for i in range(10)]
      for key in keys:
        self.ui.BindKey(
            key, (lambda k: lambda unused_event: key_pressed.put(k))(key))

      pass_input = str(random.randrange(10))
      pass_event = lambda: (not key_pressed.empty() or not self.
                            _IsDisplayConnected(args))

    self.ui.SetState([
        _('Do you see video on {display}?', display=args.display_label),
        _('Press {key} to pass the test.', key=pass_input)
    ])

    sync_utils.WaitFor(pass_event, self.args.timeout_secs)

    if not self._IsDisplayConnected(args):
      self.FailTask('Display disconnected during the test')

    if not self.buttons:
      for key in keys:
        self.ui.UnbindKey(key)

      key = key_pressed.get()
      if key != pass_input:
        self.FailTask(
            f'Wrong key pressed. pressed: {key}, correct: {pass_input}')

  def CheckVideoFixture(self, args):
    """Use fixture to check display.

    When expected connection state is observed, it pass the task.
    It probes display state every second.

    Args:
      args: ExtDisplayTaskArg instance.
    """
    check_interval_secs = 1
    retry_times = 10
    # Show light green background for Fixture's light sensor checking.
    self.ui.RunJS(
        'window.template.classList.add("green-background")')
    self.ui.SetState(
        _('Fixture is checking if video is displayed on {display}?',
          display=args.display_label))
    for num_tries in range(1, retry_times + 1):
      try:
        self._fixture.CheckExtDisplay()
        self.PassTask()
      except bft_fixture.BFTFixtureException:
        if num_tries < retry_times:
          logging.info(
              'Cannot see screen on external display. Wait for %.1f seconds.',
              check_interval_secs)
          self.Sleep(check_interval_secs)
        else:
          self.FailTask(f'Failed to see screen on external display after '
                        f'{int(retry_times)} retries.')

  def VerifyDisplayConfig(self):
    """Check display configuration.

    Verifies that the currently connected external displays is a valid
    configuration. We may have:
    - 1 internal, 1 external (e.g. chromebook)
    - 1 external (e.g. chromebox)
    - 2 external (e.g. chromebox)

    Returns:
      (current, target): current and target display ids.
    """
    display_info = self._display_manager.ListDisplayInfo()

    # Sort the current displays
    primary = []
    other = []
    internal = []
    external = []
    for info in display_info:
      if info['isInternal']:
        internal.append(info)
      else:
        external.append(info)

      if info['isPrimary']:
        primary.append(info)
      else:
        other.append(info)

    self.assertEqual(len(primary), 1, "invalid number of primary displays")
    current = primary[0]['id']

    if self.args.drm_sysfs_path:
      target_info = self._target_display_info.JoinTargetInfo(display_info)
      if target_info:
        return (current, target_info['id'])
      self.FailTask(
          f'Target {self._target_display_info!r} is not in Chrome API.')

    # Test for a valid configuration
    config = (len(internal), len(external))
    if config == (1, 1):
      target = external[0]['id']
    elif config == (0, 1):
      target = external[0]['id']
    elif config == (0, 2):
      # Select non-primary display
      target = other[0]['id']
    else:
      self.FailTask(
          f'Invalid display count: {config[0]:d} internal {config[1]:d} '
          f'external')

    return (current, target)

  def SetMainDisplay(self, display_id):
    """Sets the main display.

    Args:
      display_id: id of target display.
    """
    self._display_manager.SetMainDisplay(display_id=display_id, timeout=10)

  def SetupAudio(self, args):
    for card, action in args.init_actions:
      card = self._dut.audio.GetCardIndexByName(card)
      self._dut.audio.ApplyAudioConfig(action, card)

  def WaitConnect(self, args):
    self.ui.BindStandardFailKeys()
    self.ui.SetState(_('Connect external display: {display} and wait until '
                       'it becomes primary.',
                       display=args.display_label))

    self._WaitDisplayConnection(args, True)

  def WaitDisconnect(self, args):
    self.ui.BindStandardFailKeys()
    self.ui.SetState(
        _('Disconnect external display: {display}', display=args.display_label))
    self._WaitDisplayConnection(args, False)

  def _IsUSBPDVerified(self, args, usbpd_spec):
    """Check USBPD status before display info."""
    usbpd_verified = True
    if usbpd_spec is not None:
      usbpd_verified, mismatch = self._dut.usb_c.VerifyPDStatus(usbpd_spec)
      if usbpd_verified or 'connected' in mismatch:
        self.ui.SetInstruction('')
      elif 'polarity' in mismatch:
        self.ui.SetInstruction(
            _('Wrong USB side, please flip over {media}.',
              media=args.display_label))
      else:
        mismatch_mux = set(usb_c.MUX_INFO_VALUES) & set(mismatch)
        messages = ','.join(f'{key}={mismatch[key]}' for key in mismatch_mux)
        self.ui.SetInstruction(
            _('Wrong MUX information: {messages}.', messages=messages))
    return usbpd_verified

  def _GetInfoFromSysfs(self, display_id):
    candidates = self._dut.Glob(self.args.drm_sysfs_path)
    # Get display status from sysfs path.
    for candidate in candidates:
      card_name = os.path.basename(candidate.rstrip('/'))
      sysfs_path = self._dut.path.join(candidate, f'{card_name}-{display_id}')
      try:
        return SysfsDisplayInfo(self._dut, sysfs_path)
      except FileNotFoundError:
        # Ignore exception if status is not there.
        continue

    raise RuntimeError(
        f'No display found from drm_sysfs_path: {self.args.drm_sysfs_path}')

  def _FetchTargetInfo(self, display_id):
    target_display_info = self._GetInfoFromSysfs(display_id)
    if self._target_display_info != target_display_info:
      self._target_display_info = target_display_info
      logging.info('`cat "%s"` outputs %r', target_display_info.status_path,
                   target_display_info.status)
      logging.info('Parsing %r outputs %r', target_display_info.edid_path,
                   target_display_info.edid)

  def _IsDisplayConnected(self, args: ExtDisplayTaskArg,
                          display_info: Optional[List[Dict[str, Any]]] = None):
    """Gets connection status."""
    if self.args.drm_sysfs_path:
      display_info = display_info or self._display_manager.ListDisplayInfo()
      # Check that the target exists in Chrome API.
      return bool(self._target_display_info.JoinTargetInfo(display_info))

    # Get display status from drm_utils.
    try:
      port_info = self._dut.display.GetPortInfo()
    except ValueError as e:
      if str(e) == 'NULL pointer access':
        url = ('https://storage.googleapis.com/chromeos-factory-docs/'
               'sdk/pytests/external_display.html?highlight=drm_sysfs')
        self.FailTask(
            f'drm_sysfs_path argument is NULL. To resolve this, please '
            f'configure drm_sysfs_path. See "{url}" for more information.')
      raise
    if args.display_id not in port_info:
      self.FailTask(
          f'Display "{args.display_id}" not found. If this is an MST port, '
          f'drm_sysfs_path argument must have been set.')
    return port_info[args.display_id].connected

  def _IsDisplayDisconnected(self, args: ExtDisplayTaskArg):
    """Gets disconnection status."""
    if self.args.drm_sysfs_path:
      self._FetchTargetInfo(args.display_id)
      return self._target_display_info.status == 'disconnected'

    return not self._IsDisplayConnected(args)

  def _WaitDisplayConnection(self, args, connect):
    if self._fixture and not (connect and self.args.already_connect):
      try:
        self._fixture.SetDeviceEngaged(
            bft_fixture.BFTFixture.Device.EXT_DISPLAY, connect)
      except bft_fixture.BFTFixtureException as e:
        self.FailTask(f'Detect display failed: {e}')

    if args.usbpd_spec is None:
      usbpd_spec = None
    else:
      usbpd_spec = args.usbpd_spec.copy()
      usbpd_spec['connected'] = connect
      if 'DP' not in usbpd_spec or usbpd_spec['DP']:
        usbpd_spec['DP'] = connect

    # Waits for sysfs being ready.
    if self.args.drm_sysfs_path and connect:
      while True:
        self._FetchTargetInfo(args.display_id)
        if self._target_display_info.status == 'connected':
          break
        self.Sleep(_CONNECTION_CHECK_PERIOD_SECS)

    while True:
      display_info = self._display_manager.ListDisplayInfo()

      if self._IsUSBPDVerified(args, usbpd_spec):
        # display_info item, we assume the device's default mode is mirror
        # mode and try to turn off mirror mode.
        # On the other hand, in the case of disconnecting an external display,
        # we can not check display info has no display with 'isInternal' False
        # because any display for chromebox has 'isInternal' False.
        if connect:
          if not self._IsDisplayConnected(args, display_info):
            pass
          elif all(x['isInternal'] for x in display_info):
            self._display_manager.SetMirrorMode(
                mode=display_manager.MirrorMode.off, timeout=10)
          else:
            break
        elif self._IsDisplayDisconnected(args):
          break
      self.Sleep(_CONNECTION_CHECK_PERIOD_SECS)

    logging.info('Get display info %r', display_info)
