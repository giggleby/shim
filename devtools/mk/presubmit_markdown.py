#!/usr/bin/env python3
# Copyright 2021 The Chromium OS Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

import argparse
import sys


def main():
  parser = argparse.ArgumentParser()
  parser.add_argument('files', metavar='FILE', nargs='*',
                      help='File or directory to check.')
  args = parser.parse_args()

  def CheckTitleValid(filepath):
    with open(filepath, 'r') as f:
      rawinput = f.read().splitlines()
    codeblock = False
    titles = []
    for i, line in enumerate(rawinput):
      # Skip titles in codeblock.
      # Do strip line only when checking code block syntax to avoid:
      # "(some spaces)# TEXT"
      # and
      # (some spaces)```
      # # TEXT
      # (some spaces)```
      if not codeblock and line.strip().startswith('```'):
        codeblock = True
      elif codeblock and line.strip() == '```':
        codeblock = False
      if codeblock or len(line) == 0:
        continue

      # Two h1 header format in markdown:
      # 1. "# TITLE\n"
      # 2. "TITLE\n====="
      if i + 1 < len(rawinput) and rawinput[i + 1] == '=' * len(line):
        titles.append(line)
      elif line.startswith('# '):
        titles.append(line[2:])

    if len(titles) == 0:
      print(f'No title found in {filepath}')
      return False

    if len(titles) > 1:
      print(f'{len(titles)} titles found in {filepath}: {titles}')
      return False

    return True

  if all(
      CheckTitleValid(filepath)
      for filepath in args.files
      if filepath.endswith('.md')):
    print('Your code looks great, everything is awesome!')
  else:
    print('Markdown file should contain exactly one title line(h1 header).')
    sys.exit(1)


if __name__ == '__main__':
  main()
