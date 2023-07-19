# Copyright 2013 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Tests to manually test audio playback and record quality.

Description
-----------
This test case is a manual test to do audio functions on DUT and let operator or
engineer mark pass or fail from their own judgement.

Test Procedure
--------------
1. Operator triggers audio function on the UI.
2. Operator marks pass or fail.

Dependency
----------
- JavaScript MediaStream API

Examples
--------
To check that audio can be recorded and played, add this into test list::

  {
    "pytest_name": "audio_diagnostic"
  }

"""

from cros.factory.test import test_case
from cros.factory.test.utils import audio_utils


class AudioDiagnosticTest(test_case.TestCase):
  """A test executing audio diagnostic tools.

  This is a manual test run by operator who judges
  pass/fail result according to the heard audio quality.
  """

  related_components = (
      test_case.TestCategory.AUDIOCODEC,
      test_case.TestCategory.SMART_SPEAKER_AMPLIFIER,
      test_case.TestCategory.SPEAKERAMPLIFIER,
  )

  def setUp(self):
    """Setup CRAS and bind events to corresponding tasks at backend."""
    self.event_loop.AddEventHandler('select_cras_node', self.SelectCrasNode)

    self._cras = audio_utils.CRAS()
    self._cras.UpdateIONodes()

    self.Sleep(0.5)
    self.UpdateCrasNodes()

  def SelectCrasNode(self, event):
    node_id = event.data.get('id', '')
    self._cras.SelectNodeById(node_id)
    self.UpdateCrasNodes()

  def UpdateCrasNodes(self):
    self._cras.UpdateIONodes()
    self.ui.CallJSFunction('showCrasNodes', 'output',
                           [node.__dict__ for node in self._cras.output_nodes])
    self.ui.CallJSFunction('showCrasNodes', 'input',
                           [node.__dict__ for node in self._cras.input_nodes])

  def runTest(self):
    self.ui.CallJSFunction('init')
    self.WaitTaskEnd()
