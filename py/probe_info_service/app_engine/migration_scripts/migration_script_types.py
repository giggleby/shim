# Copyright 2022 The ChromiumOS Authors.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

import abc
import enum


class MigrationResultCase(enum.Enum):
  SUCCESS = enum.auto()
  FAILED_ROLLBACKED = enum.auto()
  FAILED_NOT_ROLLBACKED = enum.auto()


class Migrator(abc.ABC):
  """Base class for the migrators."""

  @abc.abstractmethod
  def Run(self) -> MigrationResultCase:
    """Performs the migration process."""
