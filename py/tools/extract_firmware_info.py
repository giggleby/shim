#!/usr/bin/env python3
# Copyright 2023 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

import argparse
import sys

from cros.factory.tools import finalize_bundle
from cros.factory.utils import file_utils
from cros.factory.utils import json_utils


def main():
  parser = argparse.ArgumentParser(
      description='Extract firmware info from the given ChromeOS image.')
  parser.add_argument('image',
                      help='path to the image file or rootfs partition')
  parser.add_argument('--projects', nargs="*", type=str,
                      help='specified projects to be extracted.')
  parser.add_argument('--output', '-o', type=str, help='Output file path.')
  args = parser.parse_args()

  fw_info, _ = finalize_bundle.FinalizeBundle.ExtractFirmwareInfo(
      args.image, models=args.projects)
  fw_info = json_utils.DumpStr(fw_info, pretty=True)

  if args.output:
    file_utils.WriteFile(args.output, fw_info)
  else:
    print(fw_info)


if __name__ == '__main__':
  sys.exit(main())
