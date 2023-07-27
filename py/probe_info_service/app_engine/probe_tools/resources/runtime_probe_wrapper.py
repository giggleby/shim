#!/usr/bin/env python3
# Copyright 2020 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.
"""
A standalone script that invokes the runtime probe with correct arguments
and collects back the results.
"""

import argparse
import logging
import os
import subprocess
import sys
import tempfile

import client_payload_pb2  # pylint: disable=import-error
from google.protobuf import text_format


_BUNDLE_ROOT_DIR = os.path.dirname(os.path.realpath(__file__))
_METADATA_RELPATH = 'metadata.prototxt'


def _ReadFile(path):
  with open(path, 'r', encoding='utf-8') as f:
    return f.read()


def _WriteFile(path, data):
  with open(path, 'w', encoding='utf-8') as f:
    f.write(data)


def _ResolveFilePathInBundle(relpath):
  return os.path.join(_BUNDLE_ROOT_DIR, relpath)


_RUNTIME_PROBE_NAME = 'runtime_probe'
_SUBPROC_TIMEOUT = 30
_SUBPROC_KILL_TIMEOUT = 5


def _GetRuntimeProbeUsage(runtime_probe_name):
  try:
    with subprocess.Popen([runtime_probe_name, '--help'], encoding='UTF-8',
                          stdout=subprocess.PIPE,
                          stderr=subprocess.PIPE) as proc:
      return ''.join(proc.communicate(timeout=_SUBPROC_TIMEOUT))
  except (OSError, subprocess.SubprocessError) as ex:
    logging.info('Failed to get the usage of %r (%r).', runtime_probe_name, ex)
    return ''


class RuntimeProbeNotFoundError(Exception):
  pass


def _GetRuntimeProbeInvocationCmdArgs(probe_config_file_relpath):
  runtime_probe_usage = _GetRuntimeProbeUsage(_RUNTIME_PROBE_NAME)
  if runtime_probe_usage:
    if '--verbosity_level' in runtime_probe_usage:
      return [
          _RUNTIME_PROBE_NAME,
          '--verbosity_level=3',
          '--to_stdout',
          f'--config_file_path={probe_config_file_relpath}',
      ]
    if '--log_level' in runtime_probe_usage:
      return [
          _RUNTIME_PROBE_NAME,
          '--log_level=-3',
          '--to_stdout',
          f'--config_file_path={probe_config_file_relpath}',
      ]
    raise RuntimeProbeNotFoundError(
        f'Unrecognized runtime_probe usage: {runtime_probe_usage!r}.')
  raise RuntimeProbeNotFoundError('Runtime probe binary not found.')


def _InvokeRuntimeProbe(probe_config_file_relpath):
  result = client_payload_pb2.InvocationResult()

  probe_config_real_path = _ResolveFilePathInBundle(probe_config_file_relpath)
  logging.info('Probe config file: %r.', probe_config_real_path)

  try:
    cmd_args = _GetRuntimeProbeInvocationCmdArgs(probe_config_real_path)
  except RuntimeProbeNotFoundError as ex:
    result.result_type = result.INVOCATION_ERROR
    result.error_msg = f'Failed to locate the runtime probe ({ex}).'
    logging.error(result.error_msg)
    return result

  logging.debug('Run subcommand: %r.', cmd_args)
  try:
    proc = subprocess.Popen(  # pylint: disable=consider-using-with
        cmd_args, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
        stderr=subprocess.PIPE)
  except OSError as e:
    result.result_type = result.INVOCATION_ERROR
    result.error_msg = f'Unable to invoke {cmd_args[0]!r}: {e!r}.'
    logging.error(result.error_msg)
    return result

  try:
    result.raw_stdout, result.raw_stderr = proc.communicate(
        timeout=_SUBPROC_TIMEOUT)
  except subprocess.TimeoutExpired as e:
    logging.error('Timeout for %r: %r.', cmd_args[0], e)
    result.result_type = result.TIMEOUT_ERROR
    proc.kill()
    try:
      result.raw_stdout, result.raw_stderr = proc.communicate(
          timeout=_SUBPROC_KILL_TIMEOUT)
    except subprocess.TimeoutExpired:
      proc.terminate()
      result.raw_stdout, result.raw_stderr = proc.communicate()
  else:
    result.result_type = result.FINISHED
  result.return_code = proc.returncode

  logging.info('Invocation finished, return code: %r.', proc.returncode)
  return result


def _CreateTempReportFile():
  with tempfile.NamedTemporaryFile(delete=False, prefix='probe_test_result.',
                                   suffix='.txt') as f:
    return f.name


def Main():
  ap = argparse.ArgumentParser(
      description=('Test the probe statements in the config file by '
                   'executing runtime_probe against it.'))
  ap.add_argument(
      '--output', metavar='PATH', default='', dest='output_path',
      help=('Specify the path to dump the output or "-" for outputting to '
            'stdout.  If not specified, it generates a temporary file to hold '
            'the results.'))
  ap.add_argument('--verbose', action='store_true',
                  help='Print debug log messages.')
  args = ap.parse_args()

  logging.basicConfig(level=logging.DEBUG if args.verbose else logging.INFO)

  if not args.output_path:
    args.output_path = _CreateTempReportFile()
    logging.info('Created %r to hold the final result.', args.output_path)

  metadata = text_format.Parse(
      _ReadFile(_ResolveFilePathInBundle(_METADATA_RELPATH)),
      client_payload_pb2.ProbeBundleMetadata())

  result = client_payload_pb2.ProbedOutcome(
      probe_statement_metadatas=metadata.probe_statement_metadatas,
      rp_invocation_result=_InvokeRuntimeProbe(metadata.probe_config_file_path))
  result_str = text_format.MessageToString(result)

  result_file_name = '(STDOUT)' if args.output_path == '-' else args.output_path
  logging.info('Output the final result to %r.', result_file_name)
  if args.output_path == '-':
    sys.stdout.write(result_str)
  else:
    _WriteFile(args.output_path, result_str)

  logging.info(
      'Done.  Please follow the instruction to upload %s for '
      'justification.', result_file_name)


if __name__ == '__main__':
  Main()
