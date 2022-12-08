# -*- coding: utf-8 -*-
#
# Copyright 2015 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Tests screen rotation through ChromeOS and accelerometer data.

Description
-----------
Tests that the accelerometer data matches the orientation when the device is
physically rotated.

Test Procedure
--------------
1. A picture would be shown on the screen. Operator should rotate the tablet to
   align with the image. This would repeat four times with each orientations,
   and the test automatically pass when the desired orientation is reached.

Dependency
----------
``chrome.display.system.getInfo`` in Chrome extension to get screen
information. Refer to https://developer.chrome.com/apps/system_display for
more information.

``cros.factory.device.accelerometer`` is used to determine device orientation.

Examples
--------
To test screen rotation for Chrome, add this in test list::

  {
    "pytest_name": "tablet_rotation"
  }

To test screen rotation, and have a timeout of 10 minutes::

  {
    "pytest_name": "tablet_rotation",
    "args": {
      "timeout_secs": 600
    }
  }

To provide more parameters for accelerometer when testing::

  {
    "pytest_name": "tablet_rotation",
    "args": {
      "spec_offset": [0.5, 0.5],
      "degrees_to_orientations": {
        "base": {
          "0": {
            "in_accel_x": 0,
            "in_accel_y": 1,
            "in_accel_z": 0
          },
          "90": {
            "in_accel_x": 1,
            "in_accel_y": 0,
            "in_accel_z": 0
          },
          "180": {
            "in_accel_x": 0,
            "in_accel_y": -1,
            "in_accel_z": 0
          },
          "270": {
            "in_accel_x": -1,
            "in_accel_y": 0,
            "in_accel_z": 0
          }
        }
      }
    }
  }

To test screen rotation for Chrome and prompt operator to flip before and after
the test::

  {
    "subtests": [
      {
        "pytest_name": "tablet_mode",
        "args": {
          "prompt_flip_tablet": true
        }
      },
      {
        "pytest_name": "tablet_rotation"
      },
      {
        "pytest_name": "tablet_mode",
        "args": {
          "prompt_flip_notebook": true
        }
      }
    ]
  }
"""

from cros.factory.device import device_utils
from cros.factory.test.i18n import _
from cros.factory.test import state
from cros.factory.test import test_case
from cros.factory.utils.arg_utils import Arg
from cros.factory.utils.schema import JSONSchemaDict

_TEST_DEGREES = ['90', '180', '270', '0']
_POLL_ROTATION_INTERVAL = 0.1
_VALID_LOCATIONS = ['base', 'lid']

_ARG_DEGREES_TO_ORIENTATION_SCHEMA = JSONSchemaDict(
    'degrees_to_orientation schema object', {
        'type': 'object',
        'patternProperties': {
            '(base|lid)': {
                'type': 'object',
                'patternProperties': {
                    '(0|90|180|270)': {
                        'type': 'object',
                        'patternProperties': {
                            'in_accel_(x|y|z)': {
                                'enum': [0, 1, -1]
                            }
                        },
                        'additionalProperties': False
                    }
                },
                'additionalProperties': False
            }
        },
        'additionalProperties': False
    })


class TabletRotationTest(test_case.TestCase):
  """Tablet rotation factory test."""
  ARGS = [
      Arg('timeout_secs', int, 'Timeout value for the test.', default=30),
      Arg(
          'degrees_to_orientations', dict,
          'The keys should be "base" or "lid", which are the locations of the '
          'accelerometer. And each value is a dict of (key, value) pair as '
          'follows: '
          'Keys: degrees of the orientations, ["0", "90", "180", "270"]. '
          'Values: a dictionary containing orientation configuration.  Keys '
          'should be the name of the accelerometer signal. The possible keys '
          'are "in_accel_(x|y|z)". Values should be one of [0, 1, -1], '
          'representing the ideal value for gravity under such orientation.',
          default={
              'base': {
                  '0': {
                      'in_accel_x': 0,
                      'in_accel_y': -1,
                      'in_accel_z': 0
                  },
                  '90': {
                      'in_accel_x': 1,
                      'in_accel_y': 0,
                      'in_accel_z': 0
                  },
                  '180': {
                      'in_accel_x': 0,
                      'in_accel_y': 1,
                      'in_accel_z': 0
                  },
                  '270': {
                      'in_accel_x': -1,
                      'in_accel_y': 0,
                      'in_accel_z': 0
                  }
              },
              'lid': {
                  '0': {
                      'in_accel_x': 0,
                      'in_accel_y': 1,
                      'in_accel_z': 0
                  },
                  '90': {
                      'in_accel_x': 1,
                      'in_accel_y': 0,
                      'in_accel_z': 0
                  },
                  '180': {
                      'in_accel_x': 0,
                      'in_accel_y': -1,
                      'in_accel_z': 0
                  },
                  '270': {
                      'in_accel_x': -1,
                      'in_accel_y': 0,
                      'in_accel_z': 0
                  }
              }
          }, schema=_ARG_DEGREES_TO_ORIENTATION_SCHEMA),
      Arg(
          'spec_offset', list, 'Two numbers, ex: [1.5, 1.5] '
          'indicating the tolerance for the digital output of sensors under '
          'zero gravity and one gravity.', default=[1, 1]),
      Arg('sample_rate_hz', int, 'The sample rate in Hz to get raw data from '
          'accelerometers.', default=20),
  ]

  def setUp(self):
    self.accel_controllers = {}
    self.dut = device_utils.CreateDUTInterface()
    for location, dic in self.args.degrees_to_orientations.items():
      self.accel_controllers[location] = self.dut.accelerometer.GetController(
          location=location)
      if (not set(dic).issubset(set(_TEST_DEGREES)) or
          location not in _VALID_LOCATIONS):
        self.fail(
            'Please provide proper arguments for degrees_to_orientations.')

    self.state = state.GetInstance()
    self._SetInternalDisplayRotation(0)

  def tearDown(self):
    self._SetInternalDisplayRotation(-1)

  def _GetInternalDisplayInfo(self):
    display_info = self.state.DeviceGetDisplayInfo()
    display_info = [info for info in display_info if info['isInternal']]
    if len(display_info) != 1:
      self.fail('Failed to get internal display.')
    return display_info[0]

  def _SetInternalDisplayRotation(self, degree):
    # degree should be one of [0, 90, 180, 270, -1], where -1 means auto-rotate
    display_id = self._GetInternalDisplayInfo()['id']
    self.state.DeviceSetDisplayProperties(display_id, {"rotation": degree})

  def _SetStyle(self, div_id, key, value):
    self.ui.RunJS(f'document.getElementById("{div_id}")'
                  f'.style.{key} = "{value}"')

  def _PromptAndWaitForRotation(self, degree, need_test_locations):
    while need_test_locations:
      self.Sleep(_POLL_ROTATION_INTERVAL)
      if not self._GetInternalDisplayInfo()['isAutoRotationAllowed']:
        # Auto rotation is allowed when the device is in a physical tablet
        # state or kSupportsClamshellAutoRotation is set.
        # So, if kSupportsClamshellAutoRotation is set, the value would be
        # true even if the tablet mode switch is off (false).
        # But this should be fine, because we will run the "tablet_mode" test
        # before running this test, and the test will check the "tablet mode
        # switch" in evtest.
        # To set the `kSupportsClamshellAutoRotation`, one can edit the
        # `init/goofy.d/chrome_dev.conf` and add one line to enable the option
        # `--supports-clamshell-auto-rotation`.
        self.fail('Auto rotation is not allowed.')

      for loc, dic in self.args.degrees_to_orientations.items():
        if loc not in need_test_locations:
          continue
        orientations = dic[degree]
        cal_data = self.accel_controllers[loc].GetData(
            sample_rate=self.args.sample_rate_hz)
        if self.accel_controllers[loc].IsWithinOffsetRange(
            cal_data, orientations, self.args.spec_offset):
          need_test_locations.remove(loc)
          self._SetStyle(loc, 'color', 'green')

  def runTest(self):
    self.ui.StartFailingCountdownTimer(self.args.timeout_secs)
    self.ui.SetInstruction(
        _('Rotate the tablet to correctly align the picture, holding it at '
          'an upright 90-degree angle.'))

    for degree in _TEST_DEGREES:
      need_test_locations = set()
      for loc, dic in self.args.degrees_to_orientations.items():
        if degree not in dic:
          self._SetStyle(loc, 'display', 'none')
          continue
        need_test_locations.add(loc)
        self._SetStyle(loc, 'color', '')
        self._SetStyle(loc, 'transform', f'rotate({degree}deg)')
        self._SetStyle(loc, 'display', 'block')
      if not need_test_locations:
        continue

      self.ui.SetView('main')
      self._PromptAndWaitForRotation(degree, need_test_locations)
      self.ui.SetView('success')
      self.Sleep(1)
