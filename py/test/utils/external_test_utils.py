# Copyright 2022 The ChromiumOS Authors.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.
import os

from cros.factory.utils import file_utils
from cros.factory.utils import sync_utils


class ExternalTestUtils:
  """External test utilities."""

  def __init__(self, name):
    self.name = name
    self.file_path = os.path.join('/run/factory/external', name)

  def InitTest(self):
    """Initialize the test."""
    file_dir = os.path.dirname(self.file_path)
    try:
      file_utils.TryMakeDirs(file_dir)
      os.remove(self.file_path)
    except OSError:
      if os.path.exists(self.file_path) or not os.path.exists(file_dir):
        raise

  def FileExits(self):
    """Check if the file exists."""
    return os.path.exists(self.file_path)

  def GetTestResult(self):
    """Get the test result."""
    sync_utils.PollForCondition(poll_method=self.FileExits,
                                poll_interval_secs=1, timeout_secs=None,
                                condition_name='GetExternalTestResult')

    # Ideally external hosts should do atomic write, but since it's probably
    # done by 3rd party vendors with arbitrary implementation, so a quick and
    # simple solution is to wait for one more check period so the file should be
    # flushed.
    # time.sleep in the UI thread maybe mess up the UI events, so we use a
    # separate thread to do the sleep.
    sleep = sync_utils.GetPollingSleepFunction()
    sleep(1)

    result = file_utils.ReadFile(self.file_path).strip()
    return result
