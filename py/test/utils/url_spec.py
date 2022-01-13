# Copyright 2022 The Chromium OS Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.
from cros.factory.device import device_types


class URLSpec:

  @staticmethod
  def FindServerURL(url_spec, dut: device_types.DeviceBoard):
    """Tries to parse url_spec and find a "best match URL" for a DUT.

      It is very often that partner may want to deploy multiple servers with
      different IP, and expect DUT to connect right server according to the
      DHCP IP it has received.

      Args:
        url_spec: should be a simple string as URL or a mapping from IP/CIDR to
          URL.
        dut: the returned URL will be matched by the domain of this argument.
          Usually create by calling `device_utils.CreateDUTInterface()`.
    """

    url = ''
    if isinstance(url_spec, str):
      url = url_spec
    elif isinstance(url_spec, dict):
      url = url_spec.get('default', '')
      # Sort by CIDR so smaller network matches first.
      networks = sorted(url_spec, reverse=True,
                        key=lambda k: int(k.partition('/')[-1] or 0))
      for ip_cidr in networks:
        # The command returned zero even if no interfaces match.
        if dut.CallOutput(['ip', 'addr', 'show', 'to', ip_cidr]):
          url = url_spec[ip_cidr]
          break

    if isinstance(url, str) and url:
      return url
    raise ValueError(f'Invalid url {url_spec}.')
