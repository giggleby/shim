# Copyright 2022 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

from typing import List

from cros.factory.instalog import datatypes


def CreateSimpleEvents(num: int) -> List[datatypes.Event]:
  return [datatypes.Event({'num': i}) for i in range(num)]
