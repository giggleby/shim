#!/usr/bin/env python3
# Copyright 2023 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

import argparse
import html.parser
import pathlib
from typing import List, Optional, Sequence, Tuple, cast


# pylint: disable=abstract-method
class PreSubmitHTMLParser(html.parser.HTMLParser):

  has_doctype = False
  has_html = False

  def handle_starttag(self, tag: str,
                      unused_attrs: List[Tuple[str, Optional[str]]]) -> None:
    self.has_html |= tag == 'html'

  def handle_decl(self, decl: str) -> None:
    self.has_doctype = decl == 'DOCTYPE html'


def IsQuirkMode(filepath: pathlib.Path):

  parser = PreSubmitHTMLParser()
  with filepath.open('r', encoding='utf8') as f:
    parser.feed(f.read())

  parser.close()
  return parser.has_html and not parser.has_doctype


class PreSubmitHtmlArgs:
  files: Sequence[pathlib.Path]


def main():
  parser = argparse.ArgumentParser()
  parser.add_argument('files', metavar='FILE', nargs='*', type=pathlib.Path,
                      help='Files to check.')
  args = cast(PreSubmitHtmlArgs, parser.parse_args())

  bad_files = list(filter(IsQuirkMode, args.files))
  if bad_files:
    print('HTML block should define <!DOCTYPE html>:')
    for bad_file in bad_files:
      print(f'  {bad_file}')


if __name__ == '__main__':
  main()
