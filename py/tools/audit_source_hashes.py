#!/usr/bin/env python3
# Copyright 2014 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

import argparse
import logging
import os
import shutil
import sys
import tempfile
import traceback

import yaml

from cros.factory.test.env import paths
from cros.factory.utils import file_utils
from cros.factory.utils.process_utils import Spawn


DESCRIPTION = '''
Audits source hashes logged during system finalization
to verify that no unauthorized changes have been made to
a factory bundle.  Hashes are compared against a "golden"
(known to be correct) set of hashes.

Each value for GOLDEN or SAMPLE may be any of the following:

- the 'py' directory of a factory source tree
- a factory log bundle (with name ending in '.tar.xz')
- a factory toolkit (with name ending in '.run')
- an event log file (in which case the last 'source_hashes' event
  logged is examined)

For example, to compare multiple factory logs against a "golden"
toolkit:

  audit_source_hashes --golden install_factory_toolkit.run logs/*.tar.xz
'''


class AuditException(Exception):
  pass


def GetHashes(path):
  """Gets a dictionary of hashes for the given path.

  Args:
    path: A path to any of the accepted file types (see DESCRIPTION).

  Returns:
    A dictionary of paths to their hashes.
  """
  if os.path.isdir(path):
    if os.path.basename(path) != 'py':
      raise AuditException(
          f'{path} is a directory, but not a path to a "py" source directory')
    return file_utils.HashSourceTree(path)['hashes']

  if path.endswith('.run'):
    tmpdir = tempfile.mkdtemp(prefix='toolkit.')
    try:
      # Extract and hash toolkit
      Spawn([path, '--tar', '-axf', '-C', tmpdir, './usr/local/factory/py'],
            check_call=True, log=True)
      return file_utils.HashSourceTree(
          os.path.join(tmpdir, 'usr', 'local', 'factory', 'py'))['hashes']
    finally:
      shutil.rmtree(tmpdir)

  # None of the above: it's either an event log file, or a report
  # containing an event log file.
  if path.endswith('.tar.xz'):
    # Looks like a report.  Extract the event log data.
    proc = Spawn(['tar', '-Oaxf', path, 'events'], read_stdout=True)
    if proc.returncode:
      raise AuditException(
          f'Unable to read events from report {path} (tar returned '
          f'{int(proc.returncode)})')
    data = proc.stdout_data
  else:
    # Assume it's an event log.  Look for the event specifically
    # to avoid a bunch of unnecessary YAML parsing.
    data = file_utils.ReadFile(path)

  events = data.split('\n---\n')
  for e in reversed(events):
    if not e.startswith('EVENT: source_hashes'):
      continue
    data = yaml.safe_load(e)

    hash_function = data.get('hash_function')
    if hash_function != file_utils.SOURCE_HASH_FUNCTION_NAME:
      raise ValueError(
          f'Expected hash function {file_utils.SOURCE_HASH_FUNCTION_NAME!r} but'
          f' got {hash_function!r}')
    return data['hashes']
  raise AuditException(f'No source_hashes event in event log {path}')


def FindMismatches(golden_hashes, sample_hashes, sample, out):
  error_count = [0]

  def ReportLine(path, msg):
    if error_count[0] == 0:
      out.write(f'In sample {sample}:\n')
    out.write(f'- {path}: {msg}\n')
    error_count[0] += 1

  all_keys = sorted(set(sample_hashes.keys()) |
                    set(golden_hashes.keys()))

  for k in all_keys:
    sample_value = sample_hashes.get(k)
    golden_value = golden_hashes.get(k)
    if golden_value is None and sample_value is not None:
      ReportLine(k, 'unexpected file encountered in sample')
    elif sample_value is None and golden_value is not None:
      ReportLine(k, 'missing from sample')
    elif sample_value != golden_value:
      ReportLine(
          k, f'hash mismatch (expected {golden_value}, found {sample_value})')

  return error_count[0]


def AuditHashes(golden, samples, out):
  """Audits source hashes (see DESCRIPTION).

  Args:
    golden: Path to golden used for analysis.
    samples: A list of samples to compare against.

  Returns:
    True if all values are correct, False otherwise.
  """
  golden_hashes = GetHashes(golden)

  total_bad_samples = 0
  total_mismatched_hashes = 0
  total_exceptions = 0
  for s in samples:
    try:
      sample_hashes = GetHashes(s)
      mismatched_hashes = FindMismatches(golden_hashes,
                                         sample_hashes, s, out)
    except Exception:
      out.write(f'Error processing sample {s}\n')
      traceback.print_exc(file=out)
      total_exceptions += 1
      total_bad_samples += 1
    else:
      total_mismatched_hashes += mismatched_hashes
      if mismatched_hashes:
        total_bad_samples += 1

  if total_bad_samples:
    out.write(f'\nFound {int(total_mismatched_hashes)} mismatched hashes and '
              f'{int(total_exceptions)} exceptions.\nFAILED ('
              f'{int(len(samples) - total_bad_samples)}/{len(samples)} samples '
              'passed).\n')
    return False
  out.write(f'PASSED ({len(samples)}/{len(samples)} samples passed).\n')
  return True


def main(argv=None, out=sys.stderr):
  parser = argparse.ArgumentParser(
      description=DESCRIPTION,
      formatter_class=argparse.RawDescriptionHelpFormatter)
  parser.add_argument(
      '--golden', '-g', metavar='GOLDEN',
      help='Source of "golden" (correct) hashes; defaults to this source tree')
  parser.add_argument(
      'samples', metavar='SAMPLE', nargs='+',
      help='Samples to check against the golden')
  args = parser.parse_args(sys.argv[1:] if argv is None else argv)
  logging.basicConfig(level=logging.WARNING)

  if args.golden is None:
    args.golden = os.path.join(paths.FACTORY_DIR, 'py')

  sys.exit(0 if AuditHashes(args.golden, args.samples, out) else 1)


if __name__ == '__main__':
  main()
