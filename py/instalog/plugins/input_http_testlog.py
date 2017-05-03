#!/usr/bin/python2
#
# Copyright 2017 The Chromium OS Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Input HTTP Testlog plugin.

Receives events from HTTP requests.
Can easily send one Testlog format event by curl:
$ curl -i -X POST -F 'event={Testlog JSON}' TARGET_HOSTNAME:TARGET_PORT
$ curl -i -X POST \
       -F '{
                "status": "PASSED",
                "stationInstallationId": "92228272-056e-4329-a432-64d3ed6dfa0c",
                "uuid": "8b127476-2604-422a-b9b1-f05e4f14bf72",
                "stationDeviceId": "e7d3227e-f12d-42b3-9c64-0d9e8fa02f6d",
                "type": "station.test_run",
                "testName": "webcam_test",
                "apiVersion": "0.1",
                "testRunId": "8b127472-4593-4be8-9e94-79f228fc1adc",
                "startTime": {
                    "__type__": "datetime",
                    "value": "2017-01-05T13:01:45.489000Z"},
                "time": {
                    "__type__": "datetime",
                    "value": "2017-01-05T13:01:45.503000Z"},
                "testType": "vswr",
                "seq": 8202191,
                "attachments": {
                    "front_camera.png": {
                        "description": "Image captured by the front camera.",
                        "path": "/var/factory/log/attachments/front_camera.png",
                        "mimeType": "image/png"
                    }
                }
           }' \
       -F 'front_camera.png=@/path/to/front_camera.png' \
       TARGET_HOSTNAME:TARGET_PORT

Also can send multiple events by adding header through curl:
$ curl -i -X POST \
       -F 'event={Testlog JSON}' \
       -F 'event=[{Testlog JSON}, {Attachments}]' \
       -F 'event=[{Testlog JSON}, {"0": "att_0"}]' \
       -F 'att_0=@/path/to/attachment_name' \
       -H 'Multi-Event: True' \
       TARGET_HOSTNAME:TARGET_PORT
(See datatypes.py Event.Deserialize for details of event format.)
"""

from __future__ import print_function

import instalog_common  # pylint: disable=W0611
from instalog import plugin_base
from instalog.plugins import input_http
from instalog.testlog import testlog


class InputHTTPTestlog(input_http.InputHTTP):
  def _CheckFormat(self, event):
    """Checks the event is following the Testlog format and sets attachments.

    Raises:
      Exception: the event is not conform to the Testlog format.
    """
    if 'attachments' in event:
      if len(event.attachments) != len(event['attachments']):
        raise ValueError('event[\'attachment\'] are not consistent with '
                         'attachments in requests.')
      for key in event['attachments'].iterkeys():
        if key not in event.attachments:
          raise ValueError('event[\'attachment\'] are not consistent with '
                           'attachments in requests.')
    elif len(event.attachments) != 0:
      raise ValueError('event[\'attachment\'] are not consistent with '
                       'attachments in requests.')

    # This will raise exception when the event is invalid.
    testlog.EventBase.FromDict(event.payload)
    event['__testlog__'] = True


if __name__ == '__main__':
  plugin_base.main()
