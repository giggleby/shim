#!/bin/sh
# Copyright 2016 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

# Ensure the misc/sshkeys files have right file permission 600.

FACTORY_DIR="$(readlink -f "$(dirname "$(readlink -f "$0")")/../..")"

if [ -d "${FACTORY_DIR}"/misc/sshkeys ]; then
  for f in "${FACTORY_DIR}"/misc/sshkeys/*; do
    case "${f}" in
      *.pub) ;;
      *) chmod 600 "${f}" ;;
    esac
  done
fi
