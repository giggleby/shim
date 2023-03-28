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
It runs the WebGL aquarium test, and fail if the moving average FPS value
less than 'min_fps' while testing.

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
from types import MappingProxyType

from cros.factory.test import session
from cros.factory.test import test_case
from cros.factory.utils.arg_utils import Arg


# Define in the aquarium.html of the webgl_aquarium package.
_FISH_SETTINGS = MappingProxyType({
    1: 0,
    10: 1,
    50: 2,
    100: 3,
    250: 4,
    500: 5,
    1000: 6,
})

_FACTORY_METRICS = ('moving_avg_fps', )
_TAST_METRICS = (
    'avg_fps',
    'avg_interframe_time',
    'avg_render_time',
    'std_interframe_time',
)

class WebGLAquariumTest(test_case.TestCase):
  ARGS = [
      Arg('duration_secs', int, 'Duration of time in seconds to run the test',
          default=60),
      Arg('num_fish', int,
          f'Number of fishes. Must be one of {list(_FISH_SETTINGS.keys())!r}',
          default=50),
      Arg('hide_options', bool, 'Whether to hide the options on UI',
          default=True),
      Arg('full_screen', bool, 'Whether to go full screen mode by default',
          default=True),
      Arg(
          'min_fps', int, 'Minimum moving average FPS to pass the test, '
          'if the moving average FPS is lower than it, the test will fail.'
          'The default value of it is set to 10 for warning that FPS is low.'
          'You can set it to 0 if FPS does not matter at all, '
          'or set it to a higher value for strict performance requirement.',
          default=10),
      Arg('fps_sample_interval', float, 'Period of FPS sampling in seconds',
          default=1.0),
      Arg('fps_log_interval', int, 'Period of FPS logging in seconds',
          default=60),
      Arg('fps_check_interval', int, 'Period of FPS checking in seconds',
          default=10),
      Arg('fps_window_size', int,
          'Number of FPS samples in window for calculating moving average FPS',
          default=10)
  ]

  def setUp(self):
    self.start_time = time.time()
    self.end_time = self.start_time + self.args.duration_secs
    self.metrics = dict.fromkeys(_FACTORY_METRICS + _TAST_METRICS, float("nan"))
    self.window_sum_fps = 0
    self.window_fps = collections.deque()
    num_fish: int = self.args.num_fish

    self.assertIn(num_fish, _FISH_SETTINGS)
    self.ui.CallJSFunction('setSettings', _FISH_SETTINGS[num_fish])

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
      self.metrics.update(
          (item, float(event.data.get(item))) for item in _TAST_METRICS)
    except ValueError:
      session.console.warning('Failed to get FPS from frontend. '
                              'The FPS event is skipped.')
      return

    self.window_sum_fps += fps
    self.window_fps.append(fps)
    if len(self.window_fps) == self.args.fps_window_size + 1:
      popped_fps = self.window_fps.popleft()
      self.window_sum_fps -= popped_fps
    if len(self.window_fps) == self.args.fps_window_size:
      self.metrics['moving_avg_fps'] = (
          self.window_sum_fps / self.args.fps_window_size)

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
    """Periodically logs the metrics in console."""
    time_pass = time.time() - self.start_time
    metrics_str = ', '.join(
        f'{item!r}: {value:.3f}' for item, value in self.metrics.items())
    session.console.info(f'Test time: {time_pass:.2f} seconds, {metrics_str}')

  def PeriodicCheckFPS(self):
    """Periodically checks the moving average FPS value.

    After sample FPS "fps_window_size" times, it starts to check whether
    the moving average FPS is higher or equal than the minimum FPS limit
    every seconds, if not, the test failed.
    """
    moving_avg_fps = self.metrics['moving_avg_fps']
    if moving_avg_fps < self.args.min_fps:
      self.FailTask(f'Moving Average FPS ({moving_avg_fps:.2f}) is lower than '
                    f'the limit of minimum FPS ({self.args.min_fps}).')

  def runTest(self):
    self.event_loop.AddTimedHandler(self.PeriodicCheck, 1, repeat=True)
    self.event_loop.AddTimedHandler(self.PeriodicSampleFPS,
                                    self.args.fps_sample_interval, repeat=True)
    self.event_loop.AddTimedHandler(self.PeriodicLogFPS,
                                    self.args.fps_log_interval, repeat=True)
    self.event_loop.AddTimedHandler(self.PeriodicCheckFPS,
                                    self.args.fps_check_interval, repeat=True)
    self.WaitTaskEnd()
