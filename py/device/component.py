# Copyright 2015 The Chromium OS Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

# TODO(hungte) Remove this legacy file when migration is over.

from cros.factory.device import device_types

DeviceComponent = device_types.DeviceComponent
DeviceException = device_types.DeviceException
DeviceProperty = device_types.DeviceProperty
CalledProcessError = device_types.CalledProcessError

print('You have imported cros.factory.device.component, which is deprecated by '
      'cros.factory.device.device_types. Please migrate now.')
