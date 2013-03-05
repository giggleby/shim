#!/bin/bash

# Copyright (c) 2013 The Chromium OS Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

# Script to update the active test list inside a factory test image.

. "$(dirname "$(readlink -f "$0")")/factory_common.sh" || exit 1

# Flags
DEFINE_string image "" \
  "Path to test image: /path/chromiumos_factory_test.bin" "i"
DEFINE_string list "" "Test list type like 'rma' or 'connectivity'." "l"

# Parse command line
FLAGS "$@" || exit 1
ORIGINAL_PARAMS="$@"
eval set -- "${FLAGS_ARGV}"

on_exit() {
  image_clean_temp
}

# Param checking and validation
check_file_param() {
  local param="$1"
  local msg="$2"
  local param_name="${param#FLAGS_}"
  local param_value="$(eval echo \$$1)"

  [ -n "$param_value" ] ||
    die "You must assign a file for --$param_name $msg"
  [ -f "$param_value" ] ||
    die "Cannot find file: $param_value"
}

check_parameters() {
  check_file_param FLAGS_image ""
  [[ ! -z "$FLAGS_list" ]] ||
    die "You must specify a list to make active with --list"
}

set_active_test_list() {
  local image="$(readlink -f "$1")"
  local list_name="$2"

  local temp_mount="$(mktemp -d --tmpdir)"
  local test_list="${temp_mount}/dev_image/factory/custom/test_list"
  local backup_list="${test_list}.backup"
  local target_list="${test_list}.${list_name}"
  image_add_temp "$temp_mount"

  image_mount_partition "$image" "1" "$temp_mount" "rw" ||
    die "Cannot mount partition #1 (stateful) in release image: $image"
  [ -f "$test_list" ] ||
    die "No test_list in image: $image"
  [ -f "$target_list" ] ||
    die "No target test list in image: $image"
  diff -q "${test_list}" "${target_list}" >/dev/null &&
    quit "The ${list_name} test list is already active."
  sudo cp -f "${test_list}" "${backup_list}" ||
    die "Failed to backup the test list to ${backup_list}"
  sudo cp -f "${target_list}" "${test_list}" ||
    die "Failed to copy the target list over the test_list."
  image_umount_partition "$temp_mount"
  info "Set the active test_list to ${list_name}."
}

main() {
  set -e
  trap on_exit EXIT
  if [ "$#" != 0 ]; then
    flags_help
    exit 1
  fi

  check_parameters
  # Check required tools.
  if ! image_has_part_tools; then
    die "Missing partition tools. Please install cgpt/parted, or run in chroot."
  fi

  set_active_test_list "$FLAGS_image" "$FLAGS_list"
}

main "$@"
