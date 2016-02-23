#!/usr/bin/python
#
# Copyright 2016 The Chromium OS Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

import factory_common  # pylint: disable=W0611
from cros.factory.test.dut import component


class Gyrometer(component.DUTComponent):
  """Base class for gyrometer component module."""

  def __init__(self, board):
    super(Gyrometer, self).__init__(board)

  def GetRawDataAverage(self, capture_count=1):
    """Reads several records of raw data and returns the average.

    Args:
      capture_count: how many records to read to compute the average.

    Returns:
      A dict of the format {'signal_name': average value}
    """
    raise NotImplementedError
