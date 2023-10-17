# Copyright 2014 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Factory test for lightbar on A-case.

Description
-----------

The test checks if the color of the light bar is correct for given colors.

`Here <https://chromeunboxed.com/lenovos-light-bar-toting-14-chromebook-5i-is-\
available-and-100-off>`_ is a site that introduces a chromebook with a light
bar.

Test Procedure
--------------

1. Set light bar to a color in colors_to_test.
2. The operator judges if the color is correct.
3. Go back to 1. until all the colors in colors_to_test are tested.

Dependency
----------
- ``ectool lightbar``

Examples
--------
An example::

  {
    "pytest_name": "lightbar"
  }

"""


import logging

from cros.factory.test import i18n
from cros.factory.test.i18n import _
from cros.factory.test import test_case
from cros.factory.test import test_ui
from cros.factory.utils.arg_utils import Arg
from cros.factory.utils import process_utils
from cros.factory.utils import type_utils


class LightbarTest(test_case.TestCase):
  """Factory test for lightbar on A case."""

  ARGS = [
      Arg('colors_to_test', type=list,
          help=('a list of colors to test; each element of the list is '
                '[label, [LED, RED, GREEN, BLUE]]'),
          default=[
              [_('red'), [4, 255, 0, 0]],
              [_('green'), [4, 0, 255, 0]],
              [_('blue'), [4, 0, 0, 255]],
              [_('dark'), [4, 0, 0, 0]],
              [_('white'), [4, 255, 255, 255]],
          ]),
  ]

  def setUp(self):
    self.ECToolLightbar('on')
    self.ECToolLightbar('init')
    self.ECToolLightbar('seq', 'stop')
    self.colors_to_test = [
        (i18n.Translated(label), color)
        for label, color in self.args.colors_to_test
    ]
    self.ui.ToggleTemplateClass('font-large', True)

  def tearDown(self):
    self.ECToolLightbar('seq', 'run')

  def ECToolLightbar(self, *args):
    """Calls 'ectool lightbar' with the given args.

    Args:
      args: The args to pass along with 'ectool lightbar'.

    Raises:
      TestFailure if the ectool command fails.
    """
    try:
      # Convert each arg to str to make subprocess module happy.
      args = [str(x) for x in args]
      process_utils.CheckOutput(['ectool', 'lightbar'] + args, log=True)
    except Exception as e:
      raise type_utils.TestFailure(f'Unable to set lightbar: {e}')

  def runTest(self):
    for color_label, lrgb in self.colors_to_test:
      color_name = color_label['en-US']
      logging.info('Testing %s (%s)...', color_name, lrgb)
      self.ECToolLightbar(*lrgb)
      self.ui.SetState(
          _('Is the lightbar {color}?<br>Press SPACE if yes, "F" if no.',
            color=color_label))
      key = self.ui.WaitKeysOnce([test_ui.SPACE_KEY, 'F'])
      if key == 'F':
        self.FailTask(f'Lightbar failed to light up in {color_name}')
