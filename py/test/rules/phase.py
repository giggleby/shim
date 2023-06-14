# Copyright 2014 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

import enum
import functools
import logging
import os
from typing import Optional, Union

from cros.factory.test.env import paths
from cros.factory.utils import file_utils


# Current phase; unknown at first and read lazily from
# /var/factory/state/PHASE when required.
_current_phase: Optional['Phase'] = None


class PhaseAssertionError(Exception):
  pass


class PhaseEnumMeta(enum.EnumMeta):
  """Meta class allows constructing Phase from name."""

  def __getitem__(cls, name) -> 'Phase':
    try:
      return super().__getitem__(name)
    except KeyError as err:
      raise KeyError(f'{name!r} is not a valid phase name (valid names are '
                     f'[{",".join(cls.__members__)}])') from err

  def __call__(cls, value, *args, **kwargs):
    try:
      return super().__call__(value, *args, **kwargs)
    except ValueError as err:
      values = ','.join(str(member.value) for member in iter(cls))
      raise ValueError(f'{value!r} is not a valid phase value (valid values are'
                       f' [{values}])') from err


@functools.total_ordering
class Phase(enum.Enum, metaclass=PhaseEnumMeta):
  """Object representing a build phase.

  Valid phases are PROTO, EVT, DVT, PVT_DOGFOOD, and PVT.

  - PROTO = prototype build (most forgiving; can be used for testing)
  - EVT = first build with plastics
  - DVT = second build with plastics
  - PVT_DOGFOOD = production of salable units, except that write protection
    may be disabled.  These are suitable for internal "dogfood" testing
    (https://en.wikipedia.org/wiki/Eating_your_own_dog_food), but
    non-write-protected devices may not actually be sold.
  - PVT = production of salable units
  """
  PROTO = 0
  EVT = 1
  DVT = 2
  PVT_DOGFOOD = 3
  PVT = 4

  def __str__(self):
    """A custom __str__ for hwid_rule_functions.GetPhase."""
    return self.name

  def __lt__(self, other: 'Phase'):
    if self.__class__ is not other.__class__:
      raise TypeError("'<' not supported between instances of 'Phase' and "
                      f"'{other.__class__}'")
    return self.value < other.value


PHASE_NAMES = list(Phase.__members__)
_state_root_for_testing = None


def GetPhaseStatePath():
  """Returns the path used to save the current phase."""
  return os.path.join((_state_root_for_testing or paths.DATA_STATE_DIR),
                      'PHASE')


def GetPhase():
  """Gets the current state from /var/factory/state.

  If no state has been set, a warning is logged and
  the strictest state ('PVT') is used.
  """
  global _current_phase  # pylint: disable=global-statement
  if _current_phase:
    return _current_phase

  strictest_phase = Phase[PHASE_NAMES[-1]]

  # There is a potential for a harmless race condition where we will
  # read the phase twice if GetPhase() is called twice in separate
  # threads.  No big deal.
  path = GetPhaseStatePath()
  try:
    phase = Phase[file_utils.ReadFile(path)]

    if (phase != strictest_phase and
        os.system('crossystem phase_enforcement?1 >/dev/null 2>&1') == 0):
      logging.warning('Hardware phase_enforcement activated, '
                      'enforce phase %s as %s.', phase, strictest_phase)
      phase = strictest_phase

  except IOError:
    phase = strictest_phase
    logging.warning('Unable to read %s; using strictest phase (%s)', path,
                    phase)

  _current_phase = phase
  return phase


def _CoerceToPhase(value: Union[Phase, str]):
  if isinstance(value, Phase):
    return value
  if isinstance(value, str):
    return Phase[value]
  raise TypeError(f'{value!r} is not Phase or str.')


def CoerceToPhaseOrCurrent(value: Union[Phase, str, None]):
  """Coerce value to a Phase and returns GetPhase if value is False."""
  return _CoerceToPhase(value) if value else GetPhase()


def AssertStartingAtPhase(starting_at_phase: Union[Phase, str], condition,
                          message):
  """Assert a condition at or after a given phase.

  Args:
    starting_at_phase: The phase at which to start checking this condition.
    condition: A condition to evaluate.  This may be a callable (in which
        case it is called if we're at/after the given phase), or a simple
        Boolean value.
    message: An error to include in exceptions if the check fails.  For example,
        "Expected write protection to be enabled".

  Raises:
    PhaseAssertionError: If the assertion fails.  For instance, if the ``phase``
        argument is set to ``phase.EVT``, we are currently in the DVT phase, and
        the condition evaluates to false, then we will raise an exception with
        the error message::

          Assertion starting at EVT failed (currently in DVT): Expected write
          protection to be enabled
  """
  # Coerce to an object in case a string was provided.
  starting_at_phase = _CoerceToPhase(starting_at_phase)

  current_phase = GetPhase()
  if starting_at_phase > current_phase:
    # We're not at phase yet; waive the check.
    return

  # Call the condition if it's callable (e.g., caller wants to defer an
  # expensive computation if the phase has not yet been reached)
  if callable(condition):
    condition = condition()

  if not condition:
    raise PhaseAssertionError(
        f'Assertion starting at {starting_at_phase} failed (currently in '
        f'{current_phase}): {message}')


def SetPersistentPhase(phase: Union[Phase, str, None]):
  """Sets the current phase in /var/factory/state.

  This should be invoked only by Goofy.

  Args:
    phase: The target phase. If None, the file containing the phase is deleted.
  """
  global _current_phase  # pylint: disable=global-statement

  path = GetPhaseStatePath()

  if phase:
    phase = _CoerceToPhase(phase)
    logging.info('Setting phase to %s in %s', phase, path)
    file_utils.TryMakeDirs(os.path.dirname(path))
    file_utils.WriteFile(path, phase.name)
  else:
    logging.info('Deleting phase in %s', path)
    file_utils.TryUnlink(path)

  _current_phase = phase


def OverridePhase(phase: Union[Phase, str, None]):
  """Override current phase for this process.

  This function overrides current phase of this python process. The phase is not
  saved persistently.

  Args:
    phase: The target phase. If None, the phase is reset, next GetPhase() call
        will read from persistent state again.
  """
  global _current_phase  # pylint: disable=global-statement
  if phase:
    _current_phase = _CoerceToPhase(phase)
  else:
    _current_phase = None


# Definitions for globals.  We could automatically do this based on
# PHASE_NAMES, but instead we define them manually to make lint happy.
PROTO = Phase.PROTO
EVT = Phase.EVT
DVT = Phase.DVT
PVT_DOGFOOD = Phase.PVT_DOGFOOD
PVT = Phase.PVT
