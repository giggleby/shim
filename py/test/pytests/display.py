# Copyright 2012 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Test display functionality.

Description
-----------
This test checks basic display functionality by showing colors or images on
display, and asks the operator to judge if the output looks correct.

The test can also be used to show an image for ``idle_timeout`` seconds, and
automatically pass itself after timeout is reached.

Test Procedure
--------------

``Idle mode``
If ``idle_timeout`` is set and ``symptoms`` is not set:

  1. An image is shown on the display.
  2. If the image looks incorrect, press escape key to fail the test.
  3. The test passes itself after ``idle_timeout`` seconds.

``Normal mode``
If ``idle_timeout`` and ``symptoms`` are both not set:

  1. A table of images to be tested is shown.
  2. Operator presses space key to show the image.
  3. For each image, if it looks correct, operator presses enter key to mark the
     item as passed, otherwise, operator presses escape key to mark the item as
     failed.  Operator can press space key to return to the table view.
  4. The next image would be shown after the previous one is judged.
  5. The test is passed if all items are judged as passed, and is failed if any
     item is judged as failed.

``Symptom mode``
If ``symptom`` is set and ``idle_timeout`` is not set:

  1. A table of images and symptoms to be checked is shown.
  2. For each symptom, if it is observed, click the corresponding symptom grid
     to mark it.
  3. Press enter to end the subtest. The test is passed if all symptoms are not
     marked, and is failed if any symptom is marked.
  4. The next image would be shown after the previous one is judged.
  5. The test is passed if all items are judged as passed, and is failed if any
     item is judged as failed.

Dependency
----------
Each item of ``items`` is either:
  1. ``image-<image_name>``: The corresponding <image_name> should be in the
       compressed file ``test_images.tar.bz2``. For example, if the item is
       "image-horizontal-rgbw.bmp", an image named "horizontal-rgbw.bmp"
       should be in ``test_images.tar.bz2``. We support image file formats:
       apng, avig, bmp, gif, ico, jpeg, png, svg, and webp.
  2. ``hex-color-<hex_color_code>``.
  3. A predefined CSS item listed in ``_CSS_ITEMS``.

Examples
--------
To test display functionality, add this into test list::

  {
    "pytest_name": "display"
  }

To test display functionality, show gray image, idle for an hour and pass, add
this into test list::

  {
    "pytest_name": "display",
    "args": {
      "items": ["solid-gray-127"],
      "idle_timeout": 3600
    }
  }

To test images with symptoms, add this into test list::

  {
    "pytest_name": "display",
    "args": {
      "items": [
        "image-complex.bmp",
        "solid-red",
        "hex-color-#afafaf"
      ],
      "symptoms": [
        "Symptom1",
        "Symptom2",
        "Dark Dots",
        "Light Leakage",
        "Others"
      ]
    }
  }

To test display functionality, and show some more images, add this into test
list::

  {
    "pytest_name": "display",
    "args": {
      "items": [
        "grid",
        "rectangle",
        "gradient-red",
        "image-complex.bmp",
        "image-black.bmp",
        "image-white.bmp",
        "image-crosstalk-black.bmp",
        "image-crosstalk-white.bmp",
        "image-gray-63.bmp",
        "image-gray-127.bmp",
        "image-gray-170.bmp",
        "image-horizontal-rgbw.bmp",
        "image-vertical-rgbw.bmp",
        "hex-color-#afafaf"
        "hex-color-#abc"
      ]
    }
  }

Default images in compressed file ``test_images.tar.bz2``::

 ['black.bmp',
  'complex.bmp',
  'crosstalk-black.bmp',
  'crosstalk-white.bmp',
  'gray-127.bmp',
  'gray-170.bmp',
  'gray-63.bmp',
  'horizontal-rgbw.bmp',
  'vertical-rgbw.bmp',
  'white.bmp']
"""

import os
import re

from cros.factory.test.i18n import _
from cros.factory.test.i18n import translation
from cros.factory.test import test_case
from cros.factory.test import test_ui
from cros.factory.testlog import testlog
from cros.factory.utils.arg_utils import Arg
from cros.factory.utils import file_utils


# The _() is necessary for pygettext to get translatable strings correctly.
_CSS_ITEMS = [
    _('solid-gray-170'),
    _('solid-gray-127'),
    _('solid-gray-63'),
    _('solid-red'),
    _('solid-green'),
    _('solid-blue'),
    _('solid-white'),
    _('solid-gray'),
    _('solid-black'),
    _('grid'),
    _('rectangle'),
    _('gradient-red'),
    _('gradient-green'),
    _('gradient-blue'),
    _('gradient-white')
]
_CSS_ITEMS = [x[translation.DEFAULT_LOCALE] for x in _CSS_ITEMS]
_IMAGE_PREFIX = 'image-'
_HEX_COLOR_PREFIX = 'hex-color-'

# This list is unused in this file. Just make sure the default images will be
# translated correctly.
_DEFAULT_IMAGES = [
    _('image-complex'),
    _('image-black'),
    _('image-white'),
    _('image-crosstalk-black'),
    _('image-crosstalk-white'),
    _('image-gray-63'),
    _('image-gray-127'),
    _('image-gray-170'),
    _('image-horizontal-rgbw'),
    _('image-vertical-rgbw')
]


class DisplayTest(test_case.TestCase):
  """Tests the function of display.

  Properties:
    ui: test ui.
    checked: user has check the display of current subtest.
    fullscreen: the test ui is in fullscreen or not.
    static_dir: string of static file directory.
  """
  ARGS = [
      Arg(
          'items', list,
          'Set items to be shown on screen. Available items are: items with '
          'prefix "image-" and \n' +
          '\n'.join(f'  * ``"{x}"``' for x in _CSS_ITEMS) + '\n', default=[
              'solid-gray-170', 'solid-gray-127', 'solid-gray-63', 'solid-red',
              'solid-green', 'solid-blue'
          ]),
      Arg(
          'idle_timeout', int,
          'If given, the test would be start automatically, run for '
          'idle_timeout seconds, and pass itself. '
          'Note that items should contain exactly one item in this mode.',
          default=None),
      Arg(
          'quick_display', bool,
          'If set to true, the next item will be shown automatically on '
          'enter pressed i.e. no additional space needed to toggle screen.',
          default=True),
      Arg('show_timer', bool,
          'If set to true, the timer will be shown in idle mode.',
          default=False),
      Arg('symptoms', list, 'Symptoms to check for images', default=[]),
  ]

  def setUp(self):
    """Initializes frontend presentation and properties."""
    self.static_dir = self.ui.GetStaticDirectoryPath()

    self.idle_timeout = self.args.idle_timeout
    self.items = self.args.items
    self.symptoms = self.args.symptoms

    if self.idle_timeout is not None:
      if self.symptoms:
        raise ValueError('Idle mode and symptom mode are incompatible.')
      if len(self.items) != 1:
        raise ValueError('items should have exactly one item in idle mode.')

    self.images = [
        item[len(_IMAGE_PREFIX):]
        for item in self.items
        if item.startswith(_IMAGE_PREFIX)
    ]
    if self.images:
      self.ExtractTestImages()

    invalid_hex_color_items = [
        item for item in self.items if item.startswith(_HEX_COLOR_PREFIX) and
        not self._IsHexColor(item[len(_HEX_COLOR_PREFIX):])
    ]
    if invalid_hex_color_items:
      raise ValueError(f'{invalid_hex_color_items} are not valid hex colors.')

    unknown_items = [
        item for item in set(self.items) - set(_CSS_ITEMS)
        if not item.startswith(_IMAGE_PREFIX) and
        not item.startswith(_HEX_COLOR_PREFIX)
    ]
    if unknown_items:
      raise ValueError(f'Unknown item {unknown_items!r} in items.')

    self.frontend_proxy = self.ui.InitJSTestObject('DisplayTest', self.items,
                                                   self.symptoms)
    self.checked = False
    self.fullscreen = False

  def tearDown(self):
    self.RemoveTestImages()

  def runTest(self):
    """Sets the callback function of keys."""
    self.event_loop.AddEventHandler('failed_lists',
                                    self.LogFailedListsAndFinishTask)
    self.event_loop.AddEventHandler('pass_subtest', self.OnEnterPressed)
    if self.idle_timeout is None:
      self.ui.BindKey(test_ui.SPACE_KEY, self.OnSpacePressed)
      self.ui.BindKey(test_ui.ENTER_KEY, self.OnEnterPressed)
      if not self.symptoms:
        # Fail the subtest with Escape key in Normal mode.
        self.ui.BindKey(test_ui.ESCAPE_KEY, self.OnFailPressed)
    else:
      # Idle mode
      # Automatically enter fullscreen mode in idle mode.
      self.ToggleFullscreen()
      self.ui.BindKey(test_ui.ESCAPE_KEY, self.OnFailPressed)
      self.ui.StartCountdownTimer(self.idle_timeout, self.PassTask)
      if self.args.show_timer:
        self.ui.ShowElement('display-timer')
    self.WaitTaskEnd()

  def ExtractTestImages(self):
    """Extracts selected test images from test_images.tar.bz2."""
    file_utils.ExtractFile(os.path.join(self.static_dir, 'test_images.tar.bz2'),
                           self.static_dir, only_extracts=self.images)

  def RemoveTestImages(self):
    """Removes extracted image files after test finished."""
    for image in self.images:
      file_utils.TryUnlink(os.path.join(self.static_dir, image))

  def OnSpacePressed(self, event):
    """Sets self.checked to True. Calls JS function to switch display on/off."""
    del event  # Unused.
    self.ToggleFullscreen()

  def OnEnterPressed(self, event):
    """Passes the subtest only if self.checked is True."""
    del event  # Unused.
    if self.checked:
      if not self.symptoms:
        self.frontend_proxy.JudgeSubTest(True)
      else:
        self.frontend_proxy.JudgeSubTestWithSymptom()
      # If the next subtest will be in fullscreen mode, checked should be True
      self.checked = self.fullscreen
      if self.args.quick_display and not self.fullscreen:
        self.ToggleFullscreen()

  def OnFailPressed(self, event):
    """Fails the subtest only if self.checked is True."""
    del event  # Unused.
    if self.checked:
      self.frontend_proxy.JudgeSubTest(False)
      # If the next subtest will be in fullscreen mode, checked should be True
      self.checked = self.fullscreen

  def LogFailedListsAndFinishTask(self, event):
    failed_items = event.data[0]
    failed_symptoms = event.data[1]

    if failed_symptoms:
      failed_item_symptom = [
          f'{failed_items[i]}: {", ".join(failed_symptoms[i])}'
          for i in range(len(failed_items))
      ]
      testlog.LogParam('display_test_failed_list', failed_item_symptom)
      self.FailTask(
          f'Display test failed. Failed items and the corresponding symptoms:'
          f'{failed_item_symptom}')
    if failed_items:
      testlog.LogParam('display_test_failed_list', failed_items)
      self.FailTask(f'Display test failed. Failed items: {failed_items}')
    self.PassTask()

  def ToggleFullscreen(self):
    self.checked = True
    self.frontend_proxy.ToggleFullscreen()
    self.fullscreen = not self.fullscreen

  @classmethod
  def _IsHexColor(cls, color_code):
    pattern = r'#([0-9a-fA-F]{3}|[0-9a-fA-F]{6})'
    return re.fullmatch(pattern, color_code)
