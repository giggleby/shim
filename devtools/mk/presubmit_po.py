#!/usr/bin/env python3
# Copyright 2022 The Chromium OS Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

import argparse
import glob
import os
import shutil
import subprocess
import sys
import tempfile


def main():
  parser = argparse.ArgumentParser()
  parser.add_argument('po_path', help='Po directory path.')
  args = parser.parse_args()

  po_files = glob.glob(os.path.join(args.po_path, '*.po'))
  outdated_files = []

  with tempfile.TemporaryDirectory(prefix='po_update_test.') as test_po_dir:
    TryUpdate(args.po_path, test_po_dir, po_files)
    for po_file in po_files:
      po_basename = os.path.basename(po_file)
      if not IsPoFileUpToDate(po_file, os.path.join(test_po_dir, po_basename)):
        outdated_files.append(po_file)

  if not outdated_files:
    print('Your code looks great, everything is awesome!')
  else:
    print(f"Files {outdated_files!r} are not updated, please run 'make -C po "
          "update' inside chroot and check the translations.")
    sys.exit(1)


def TryUpdate(po_path, test_po_dir, po_files):
  for po_file in po_files:
    shutil.copy(po_file, test_po_dir)

  env = {
      'PO_DIR': test_po_dir
  }
  try:
    subprocess.run(['make', '-C', po_path, 'update'], stdout=subprocess.DEVNULL,
                   stderr=subprocess.PIPE, check=True, env=env)
  except subprocess.CalledProcessError as e:
    print(f'Try update failed: {e.stderr.decode("utf-8")}')
    raise e


def IsPoFileUpToDate(old_path, new_path):
  with open(old_path, encoding='utf8') as old_po_f, open(
      new_path, encoding='utf8') as new_po_f:
    old_content = old_po_f.readlines()
    new_content = new_po_f.readlines()

  if len(old_content) != len(new_content):
    return False

  for old_line, new_line in zip(old_content, new_content):
    if old_line != new_line:
      # PO-Revision-Date is updated every time, so difference in this line does
      # not mean content is outdated.
      revision_line = 'PO-Revision-Date'
      if revision_line in old_line and revision_line in new_line:
        continue
      return False

  return True


if __name__ == '__main__':
  main()
