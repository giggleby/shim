# Copyright 2021 The Chromium OS Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

import logging

from cros.factory.external import cv2 as cv
from cros.factory.external import numpy as np


# Instead of using fix-length grid, we specify the grid ratio.
# This way the boundary area is fixed under different camera resolutions.
# We also use different shapes of grid to detect black edges.
GRID_RATIO = ((0.05, 0.03), (0.025, 0.015), (0.0125, 0.0225), (0.0375, 0.0075))
# MAX_GRID_RATIO is used to draw the approximate detection region on UI.
MAX_GRID_RATIO = (max(x for x, _ in GRID_RATIO), max(y for _, y in GRID_RATIO))


class DetectCameraAssemblyIssue:
  """Detect the camera assembly issue by checking the luminance of an image.

  The boundary region of the image taken from badly assembled camera tends to be
  darker or having black edges. If the luminance value of the boundary region is
  lower than a predefined threshold, we consider the camera being badly
  assembled.
  """

  def __init__(self, cv_image, min_luminance_ratio=0.5):
    """Constructor of DetectCameraAssemblyIssue.

    Args:
      cv_image: OpenCV color image
      min_luminance_ratio: the minimum acceptable luminance of the boundary
                           region
    """
    self.cv_image = cv.cvtColor(cv_image, cv.COLOR_BGR2GRAY)
    self.cv_color_image = cv_image
    self.img_height, self.img_width = self.cv_image.shape
    self.min_luminance_ratio = min_luminance_ratio

  def _AveragePooling(self, grid_height, grid_width):
    """Map N*M image to n*m grids by averaging the pixel values in the grids.
    """
    # Calculate the ceiling of (img_width / grid_width)
    num_horizontal_grid = (self.img_width // grid_width) + (
        self.img_width % grid_width != 0)
    num_vertical_grid = (self.img_height // grid_height) + (
        self.img_height % grid_height != 0)

    # Calculate which pixel belongs to which grid
    grid_row_idx = np.arange(0, self.img_height) // grid_height
    grid_row_idx = np.clip(grid_row_idx, None, num_vertical_grid - 1)
    grid_col_idx = np.arange(0, self.img_width) // grid_width
    grid_col_idx = np.clip(grid_col_idx, None, num_horizontal_grid - 1)

    # We use bin count to calculate the sum of pixel values in each grid.
    # Moreover, since numpy.bincount only accept 1d index, we turn the 2d index
    # into 1d index.

    # Shape of two_d_row_idx, two_d_col_idx = (img_height, img_width)
    two_d_row_idx, two_d_col_idx = np.meshgrid(grid_col_idx, grid_row_idx)
    two_d_idx = two_d_row_idx + two_d_col_idx * num_horizontal_grid
    one_d_idx = two_d_idx.flatten()
    sum_grid_vals = np.bincount(one_d_idx, weights=self.cv_image.flatten())

    # Calculate the number of pixels in each grid
    one_d_ones_array = np.ones((self.img_height * self.img_width), dtype=int)
    num_pixels_each_grid = np.bincount(one_d_idx, weights=one_d_ones_array)

    avg_grid_vals = sum_grid_vals / num_pixels_each_grid
    avg_grid_vals = avg_grid_vals.reshape(num_vertical_grid,
                                          num_horizontal_grid)

    return avg_grid_vals

  def _CalculateBrightThresByKMeans(self, avg_grid_vals):
    """Calculate the `bright` threshold value by K-means.

    K-means method splits the pixel values into 2 groups, one for bright
    group another for dark group. We pick the center of bright group as
    `bright` threshold value.
    K-means is slower since it needs to run several iterations to converge.
    Therefore, instead of using raw pixels, we use averaged grid values to
    speed up the process.

    Args:
      avg_grid_vals: The average grid pixel value for the input image.

    Returns:
      The `bright` threshold value.
    """
    img_flatten = avg_grid_vals.astype('float32').flatten()
    criteria = (cv.TERM_CRITERIA_EPS + cv.TERM_CRITERIA_MAX_ITER, 10, 0.1)
    _, _, centers = cv.kmeans(img_flatten, 2, None, criteria, 10,
                              cv.KMEANS_RANDOM_CENTERS)

    return int(max(centers))

  def _CalculateBrightThresByCenter(self, avg_grid_vals):
    """Calculate the `bright` threshold value by center grid.

    For center grid method, we average the pixel value of the center grid
    and output as `bright` threshold value. The intuition is that the
    center region is usually the brightest among all other regions.

    Args:
      avg_grid_vals: The average grid pixel value for the input image.

    Returns:
      The `bright` threshold value.
    """
    num_vertical_grid, num_horizontal_grid = avg_grid_vals.shape

    # Calculate the average pixel value of the center grid.
    center_vertical_grid = num_vertical_grid // 2
    center_horizontal_grid = num_horizontal_grid // 2

    # Calculate the average grid values if grid num is even.
    vertical_grid_start = center_vertical_grid - (num_vertical_grid % 2 == 0)
    horizontal_grid_start = center_horizontal_grid - (
        num_horizontal_grid % 2 == 0)
    center_grid_avg_val = 0
    num_grids = 0
    for i in range(vertical_grid_start, center_vertical_grid + 1):
      for j in range(horizontal_grid_start, center_horizontal_grid + 1):
        center_grid_avg_val += avg_grid_vals[i][j]
        num_grids += 1
    center_grid_avg_val //= num_grids

    return center_grid_avg_val

  def IsBoundaryRegionTooDark(self, use_center=True):
    """Check whether the luminance of the boundary grids are too low.

    We divide the image into different kinds of n*m grids and averaging the
    pixel value of each grid. If the pixel value of the boundary grids is lower
    than or equal to `min_luminance_value`, then the image is likely to contain
    black edges, and thus the camera is badly assembled.
    The `min_luminance_value` is calculated by multiplying `bright` threshold
    with `min_luminance_ratio`. For instance, if the `bright` threshold is 150
    and the min_luminance_ratio is 0.5, then boundary grids lower than or equal
    to 75 are rejected.

    Args:
      use_center: use center grid to calculate the `bright` threshold or not.
        If set to false, the `bright` threshold is calculated by K-means.

    Returns:
      A tuple of boolean, 2d array and a tuple
      boolean: The boundary is too dark or not
      2d array: n*m bool grids which represents each grid is too dark or not
      tuple: The width and height of each grid
    """
    for grid_height_ratio, grid_width_ratio in GRID_RATIO:
      grid_height = int(grid_height_ratio * self.img_height)
      grid_width = int(grid_width_ratio * self.img_width)
      avg_grid_vals = self._AveragePooling(grid_height, grid_width)

      if use_center:
        bright_luminance_value = \
          self._CalculateBrightThresByCenter(avg_grid_vals)
      else:
        bright_luminance_value = \
          self._CalculateBrightThresByKMeans(avg_grid_vals)

      min_luminance_value = bright_luminance_value * self.min_luminance_ratio
      logging.info('Luminance value threshold %d', min_luminance_value)
      grid_is_too_dark = avg_grid_vals <= min_luminance_value
      # We mask out the center region since we only check if the boundary
      # region is too dark.
      grid_is_too_dark[1:-1, 1:-1] = False
      is_too_dark = np.any(grid_is_too_dark)
      if is_too_dark:
        return is_too_dark, grid_is_too_dark, (grid_width, grid_height)

    return False, None, None


def GetQRCodeDetectionRegion(img_height, img_width):
  """Calculate the detection region using the shape of the grid.

  Returns:
    The x, y coordinates, width and height of the detection region.
  """
  y_pos = int(MAX_GRID_RATIO[0] * img_height)
  x_pos = int(MAX_GRID_RATIO[1] * img_width)
  width = img_width - x_pos * 2
  height = img_height - y_pos * 2

  return x_pos, y_pos, width, height
