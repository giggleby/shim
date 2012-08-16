#!/usr/bin/python
#
# Copyright (c) 2012 The Chromium OS Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

import argparse
import logging
import os
import re
import subprocess
import sys

import factory_common  # pylint: disable=W0611
from cros.factory.test import utils
from cros.factory.tools.mount_partition import MountPartition
from cros.factory.utils.process_utils import Spawn

STATEFUL_PARTITION_INDEX = 1

BLACKLIST = map(re.compile, [
    'autotest/deps/',
    'autotest/site_tests/.+/src/',
    'autotest/site_tests/audiovideo_V4L2/media_v4l2_.*test$',
    ])

def main():
  parser = argparse.ArgumentParser(
      description=("Compares the autotest and factory directories in "
                   "two partitions."))
  parser.add_argument('--verbose', '-v', action='count')
  parser.add_argument('images', metavar='IMAGE', nargs=2)
  args = parser.parse_args()
  logging.basicConfig(level=logging.WARNING - 10 * (args.verbose or 0))

  mount_points = ['/tmp/diff_image_1', '/tmp/diff_image_2']
  for f in mount_points:
    utils.TryMakeDirs(f)
  with MountPartition(args.images[0], STATEFUL_PARTITION_INDEX,
                      mount_points[0]):
    with MountPartition(args.images[1], STATEFUL_PARTITION_INDEX,
                        mount_points[1]):
      for d in ['autotest', 'factory']:
        process = Spawn(
            ['diff', '-qr'] +
            # Skip client directory in autotest, since it causes a recursive
            # directory loop in diff.  This isn't perfect since it skips
            # *everything* called client, but it'll do.
            (['-x', 'client'] if d == 'autotest' else []) +
            [os.path.join(x, 'dev_image', d) for x in mount_points],
            read_stdout=True, log=True,
            check_call=lambda returncode: returncode in [0,1])
        output = process.stdout_data
        for line in output.strip().split('\n'):
          match = re.match('^Files (.+) and (.+) differ$|'
                           '^Only in (.+): (.+)$|',
                           line)
          assert match, 'Weird line in diff output: %r' % line

          if match.group(1):
            # Files exist in both trees, but differ
            paths = [match.group(1), match.group(2)]
          else:
            assert match.group(3)
            path = os.path.join(match.group(3), match.group(4))
            if path.startswith(mount_points[0]):
              paths = [path, None]
            elif path.startswith(mount_points[1]):
              paths = [None, path]
            else:
              assert False, (
                  "path doesn't start with either of %s" % mount_points)

          stripped_paths = []
          for i in (0, 1):
            if paths[i]:
              prefix = os.path.join(mount_points[i], 'dev_image', '')
              assert paths[i].startswith(prefix)
              # Strip the prefix
              stripped_paths.append(paths[i][len(prefix):])

          assert all(x == stripped_paths[0] for x in stripped_paths), (
              stripped_paths)

          stripped_path = stripped_paths[0]

          blacklist_matches = [x for x in BLACKLIST
                               if x.match(stripped_path)]
          if blacklist_matches:
            logging.debug('Skipping %s since it matches %r',
                          stripped_path,
                          [x.pattern for x in blacklist_matches])
            continue

          def PrintHeader(message):
            print
            print '*** %s' % stripped_path
            print '*** %s' % message

          if any(x is None for x in paths):
            # We only have one or the other
            PrintHeader('Only in image%d' % (1 if paths[0] else 2))
            continue

          # It's a real difference.  Are either or both symlinks?
          is_symlink = map(os.path.islink, paths)
          if is_symlink[0] != is_symlink[1]:
            # That's a difference.
            # pylint: disable=E9906
            PrintHeader('%s symlink in image1 but %s in image2' %
                        ('is' if x else 'is not' for x in is_symlink))
          elif is_symlink[0]:
            link_paths = map(os.readlink, paths)
            if link_paths[0] != link_paths[1]:
              PrintHeader('symlink to %r in image1 but %r in image2' %
                          tuple(link_paths))
          else:
            # They're both regular files; print a unified diff of the
            # contents.
            process = Spawn(
                ['diff', '-u'] + paths,
                check_call=lambda returncode: returncode in [0,1,2],
                read_stdout=True)
            if process.returncode == 2:
              if re.match('Binary files .+ differ\n$', process.stdout_data):
                PrintHeader('Binary files differ')
              else:
                raise subprocess.CalledProcessError(process.returncode,
                  process.args)
            else:
              PrintHeader('Files differ; unified diff follows')
              sys.stdout.write(process.stdout_data)

if __name__ == '__main__':
  main()
