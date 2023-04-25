# Copyright 2013 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Encapsulates QR Barcode scanner."""

import logging

from cros.factory.external.py_lib import cv2 as cv
from cros.factory.external.py_lib import numpy as np
from cros.factory.external.py_lib import zbar

if not zbar.MODULE_READY:
  logging.warning('zbar is not installed')


def ScanQRCode(cv_image):
  """Encodes OpenCV image to common image format.

  Args:
    cv_image: OpenCV color image.

  Returns:
    List of scanned text.
  """
  width, height = cv_image.shape[1], cv_image.shape[0]
  raw_str = cv.cvtColor(cv_image, cv.COLOR_BGR2GRAY).astype(np.uint8).tostring()

  scanner = zbar.ImageScanner()
  scanner.set_config(zbar.Symbol.QRCODE, zbar.Config.ENABLE, 1)
  zbar_img = zbar.Image(width, height, 'Y800', raw_str)
  scanner.scan(zbar_img)

  return [symbol.data for symbol in zbar_img]
