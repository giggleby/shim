#!/usr/bin/env python3
# Copyright 2020 The Chromium OS Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

import argparse
import fnmatch
import json
import multiprocessing.pool
import os
import shutil
import subprocess
import sys
import tempfile

import presubmit_common

# Paths of venv and yapf.
SCRIPT_DIR = os.path.dirname(__file__)
VENV_DIR = os.path.join(SCRIPT_DIR, 'yapf.venv')
VENV_REQUIREMNTS_FILE = os.path.join(SCRIPT_DIR, 'yapf.requirements.txt')
VENV_BIN = os.path.join(VENV_DIR, 'bin')
YAPF_STYLE_PATH = os.path.join(SCRIPT_DIR, 'style.yapf')


def InstallRequirements():
  subprocess.check_call([
      os.path.join(VENV_BIN, 'pip'), 'install', '--force-reinstall', '-r',
      VENV_REQUIREMNTS_FILE
  ])


def MakeVirtualEnv():
  os.mkdir(VENV_DIR)
  subprocess.check_call(
      ['virtualenv', '--system-site-package', '-p', 'python3', VENV_DIR])
  InstallRequirements()


def CheckVirtualEnv():
  if not os.path.exists(VENV_DIR):
    MakeVirtualEnv()

  current_version = subprocess.check_output([
      os.path.join(VENV_BIN, 'pip'), 'freeze', '--local', '-r',
      VENV_REQUIREMNTS_FILE
  ],
                                            encoding='utf-8')
  with open(VENV_REQUIREMNTS_FILE, encoding='utf8') as f:
    expected_version = f.read()
  if current_version[:current_version.find('\n##') + 1] != expected_version:
    InstallRequirements()


def _ProcessOneFile(args):
  base_cmd, file_path, ranges, work_tree = args
  range_args = []

  has_formattable_lines = False
  for diff_start, diff_len in ranges:
    diff_end = diff_start + diff_len - 1
    if diff_end >= diff_start:
      has_formattable_lines = True
      range_args += ['-l', '{}-{}'.format(diff_start, diff_end)]

  if has_formattable_lines:
    if work_tree:
      work_tree_file_path = os.path.join(work_tree, file_path)
    else:
      work_tree_file_path = file_path
    if subprocess.call(base_cmd + [work_tree_file_path] + range_args) != 0:
      return file_path
  return None


def main():
  parser = argparse.ArgumentParser()
  parser.add_argument(
      '--fix', action='store_true', help='Make change to the files in place.')
  parser.add_argument(
      '--commit', help='Only check changed lines of a git commit.')
  parser.add_argument(
      '--rules_file',
      metavar='RULES_FILE',
      default=os.path.join(SCRIPT_DIR, 'presubmit_format.json'),
      help=('A JSON file contains a shebang allow list and a file exclusion '
            'list.'))
  parser.add_argument(
      'files', metavar='FILE', nargs='*', help='File or directory to check.')
  args = parser.parse_args()

  CheckVirtualEnv()

  with open(args.rules_file, encoding='utf8') as f:
    rules = json.load(f)
  exclude_patterns = set(rules['exclude_patterns'])

  is_not_head_commit = False
  if args.commit and args.commit != 'HEAD':
    log_cmd = ['git', 'log', '-1', '--pretty=format:%H']
    current_commit_hash = subprocess.check_output(log_cmd + [args.commit],
                                                  encoding='utf-8')
    head_commit_hash = subprocess.check_output(log_cmd, encoding='utf-8')
    is_not_head_commit = current_commit_hash != head_commit_hash

    if args.fix and is_not_head_commit:
      print(f'Cannot fix non-HEAD commit. commit: {current_commit_hash!r} '
            f'head: {head_commit_hash!r}')
      sys.exit(1)

  base_cmd = [
      os.path.join(VENV_BIN, 'yapf'), '--in-place' if args.fix else '--quiet',
      '--style', YAPF_STYLE_PATH
  ]

  line_diffs = presubmit_common.ComputeDiffRange(args.commit, args.files)

  def ShouldExclude(file_path):
    return any(
        fnmatch.fnmatch(file_path, pattern) for pattern in exclude_patterns)

  # Only check filenames end with '.py'.  We filter these again in case
  # args.files is an empty list, in this case, line_diffs will be all files
  # changed by args.commit.
  files = [f for f in line_diffs if f.endswith('.py') and not ShouldExclude(f)]

  if is_not_head_commit:
    # Checkout to the commit before we format.
    work_tree = tempfile.mkdtemp(prefix='factory_pre_submit_format')
    with subprocess.Popen(['git', 'archive', args.commit] + files,
                          stdout=subprocess.PIPE) as ps:
      subprocess.run(['tar', '-x', '-C', work_tree], check=True,
                     stdin=ps.stdout)
  else:
    work_tree = None

  proc_args = [(base_cmd, f, line_diffs[f], work_tree) for f in files]
  with multiprocessing.pool.ThreadPool() as pool:
    failed_files = list(filter(None, pool.imap(_ProcessOneFile, proc_args)))

  if is_not_head_commit:
    shutil.rmtree(work_tree)

  if failed_files:
    print('Please format your code before submitting for review.')
    fix_cmd = ['make', 'format', 'FILES="{}"'.format(' '.join(failed_files))]
    if args.commit:
      fix_cmd.append('COMMIT=HEAD')
    fix_cmd = ' '.join(fix_cmd)
    if is_not_head_commit:
      print('Please run the following command (in chroot) and then rebase: '
            f'`git checkout {args.commit} && {fix_cmd}`')
    else:
      print(f'Please run (in chroot): `{fix_cmd}`')
    sys.exit(1)
  else:
    print('Your code looks great, everything is awesome!')


if __name__ == '__main__':
  main()
