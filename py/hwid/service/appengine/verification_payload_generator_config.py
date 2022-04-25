# Copyright 2022 The Chromium OS Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.
"""Classes defining configs for the verification payload generator."""

from typing import List, NamedTuple, Optional


class VerificationPayloadGeneratorConfig(NamedTuple):
  """A class to describe configs for the verification payload generator.

  Attributes:
    board: The name of the board.
    waived_comp_categories: The list of component categories which means their
        verification payload will not be generated.
  """

  board: str
  waived_comp_categories: List[str]

  @classmethod
  def Create(
      cls, board: str = "", waived_comp_categories: Optional[List[str]] = None
  ) -> 'VerificationPayloadGeneratorConfig':
    if waived_comp_categories is None:
      waived_comp_categories = []

    return cls(board=board, waived_comp_categories=waived_comp_categories)
