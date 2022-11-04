# Copyright 2013 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""WebGL performance test that executes a set of WebGL operations.

Description
-----------
The test runs the WebGL aquarium test for testing the 3D hardware-accelerated
JavaScript API 'WebGL', and get FPS value from frontend for checking.

Test Procedure
--------------
This is an automatic test that doesn't need any user interaction.
Just set the argument before start, and wait for the completion.

"min_fps" argument is the minimum average FPS to pass the test, if the average
FPS is lower than it, the test will fail, the default value of it is set to 10
for warning that FPS is low.
You can set it to 0 if FPS doesn't matter at all, or set it to a higher value
for strictly performance requirement.

Dependency
----------
None.

Examples
--------
To disable the performance restriction, add this in test list::

  {
    "pytest_name": "webgl_aquarium",
    "args": {
      "min_fps": 0
    }
  }

To sample and check FPS more frequently with higher standard for FPS,
add this in test list::

  {
    "pytest_name": "webgl_aquarium",
    "args": {
      "min_fps": 30,
      "fps_sample_interval": 0.5,
      "fps_check_interval": 3
    }
  }
"""

import collections
import time

from cros.factory.test import session
from cros.factory.test import test_case
from cros.factory.utils.arg_utils import Arg


class WebGLAquariumTest(test_case.TestCase):
  ARGS = [
      Arg('duration_secs', int, 'Duration of time in seconds to run the test',
          default=60),
      Arg('hide_options', bool, 'Whether to hide the options on UI',
          default=True),
      Arg('full_screen', bool, 'Whether to go full screen mode by default',
          default=True),
      Arg('min_fps', int, 'Minimum average FPS to pass the test', default=10),
      Arg('fps_sample_interval', float, 'Period of FPS sampling in seconds',
          default=1.0),
      Arg('fps_log_interval', int, 'Period of FPS logging in seconds',
          default=60),
      Arg('fps_check_interval', int, 'Period of FPS checking in seconds',
          default=10),
      Arg('fps_window_size', int,
          'Number of FPS samples in window for calculating average FPS',
          default=10)
  ]

  def setUp(self):
    self.start_time = time.time()
    self.end_time = self.start_time + self.args.duration_secs
    self.sum_fps = 0
    self.window_fps = collections.deque()

    if self.args.full_screen:
      self.ui.CallJSFunction('toggleFullScreen')

    # bind function 'self.AddFPSToWindow' with 'AddFPSToWindow' event.
    self.event_loop.AddEventHandler('AddFPSToWindow', self.AddFPSToWindow)

  def FormatSeconds(self, secs):
    hours = int(secs / 3600)
    minutes = int((secs / 60) % 60)
    seconds = int(secs % 60)
    return f'{int(hours):02}:{int(minutes):02}:{int(seconds):02}'

  def PeriodicCheck(self):
    time_left = self.end_time - time.time()
    if time_left <= 0:
      self.PassTask()
    self.ui.CallJSFunction('updateUI', self.FormatSeconds(time_left),
                           self.args.hide_options)

  def AddFPSToWindow(self, event):
    """Adds the fps value received from frontend into window (FIFO queue)."""
    try:
      fps = int(event.data.get('webgl_fps'))
    except ValueError:
      session.console.warning('Failed to get FPS from frontend. '
                              'The FPS event is skipped.')
      return

    self.sum_fps += fps
    self.window_fps.append(fps)
    if len(self.window_fps) == self.args.fps_window_size + 1:
      popped_fps = self.window_fps.popleft()
      self.sum_fps -= popped_fps

  def PeriodicSampleFPS(self):
    """Periodicly samples FPS value from WebGL Aquarium test.

    This method starts to get FPS value after 5 sec since webGL start,
    it's for preventing from getting unstable FPS value.
    This method will be called every "fps_sample_interval" seconds.
    """
    time_pass = time.time() - self.start_time
    if time_pass >= 5:
      self.ui.CallJSFunction('sendFpsToPytest')

  def PeriodicLogFPS(self):
    """Periodicly logs the average FPS value in console."""
    if len(self.window_fps) == self.args.fps_window_size:
      avg_fps = self.sum_fps / self.args.fps_window_size
      time_pass = time.time() - self.start_time
      session.console.info(
          f'Test time: {time_pass:.2f} seconds, Average FPS: {avg_fps:.2f}')

  def PeriodicCheckFPS(self):
    """Periodicly checks the average FPS value.

    After sample FPS "fps_window_size" times, it starts to check whether
    the average FPS in window is higher or equal than the minimum FPS limit
    every seconds, if not, the test failed.
    """
    if len(self.window_fps) == self.args.fps_window_size:
      avg_fps = self.sum_fps / self.args.fps_window_size
      if avg_fps < self.args.min_fps:
        self.FailTask(f'Average FPS ({avg_fps:.2f}) is lower than the limit '
                      f'of minimum FPS ({self.args.min_fps}).')

  def runTest(self):
    self.event_loop.AddTimedHandler(self.PeriodicCheck, 1, repeat=True)
    self.event_loop.AddTimedHandler(self.PeriodicSampleFPS,
                                    self.args.fps_sample_interval, repeat=True)
    self.event_loop.AddTimedHandler(self.PeriodicLogFPS,
                                    self.args.fps_log_interval, repeat=True)
    self.event_loop.AddTimedHandler(self.PeriodicCheckFPS,
                                    self.args.fps_check_interval, repeat=True)
    self.WaitTaskEnd()
