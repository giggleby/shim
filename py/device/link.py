# Copyright 2015 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

# TODO(hungte) Remove this legacy file when migration is over.

from cros.factory.device import device_types


DeviceLink = device_types.IDeviceLink

print('You have imported cros.factory.device.link, which is deprecated by '
      'cros.factory.device.device_types. Please migrate now.')
