#!/bin/bash

# Copyright 2013 The Chromium OS Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

# Allows editing contents of lsb-factory file from a disk image.

. "$(dirname "$(readlink -f "$0")")/factory_common.sh" || exit 1

# Flags
DEFINE_string image "" \
  "Path to factory install image: /path/image.bin" "i"

# Parse command line
FLAGS "$@" || exit 1
eval set -- "${FLAGS_ARGV}"

# Constants
FLAG_CUTOFF_METHOD="CUTOFF_METHOD"
FLAG_CUTOFF_AC_STATE="CUTOFF_AC_STATE"
FLAG_CUTOFF_BATTERY_MIN_PERCENTAGE="CUTOFF_BATTERY_MIN_PERCENTAGE"
FLAG_CUTOFF_BATTERY_MAX_PERCENTAGE="CUTOFF_BATTERY_MAX_PERCENTAGE"
FLAG_CUTOFF_BATTERY_MIN_VOLTAGE="CUTOFF_BATTERY_MIN_VOLTAGE"
FLAG_CUTOFF_BATTERY_MAX_VOLTAGE="CUTOFF_BATTERY_MAX_VOLTAGE"
FLAG_SHOPFLOOR_URL="SHOPFLOOR_URL"

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
}

replace_or_append() {
  local key="$1"
  local value="$2"
  local edit_file="$3"

  local current="$(sed -n "/^$key=/p" "$edit_file")"
  if [ -z "$current" ]; then
    echo "$key=$value" >> "$edit_file"
  else
    sed -i "s'^$key=.*'$key=$value'g" "$edit_file"
  fi
}

remove_flag() {
  local key="$1"
  local edit_file="$2"

  sed -i "/^$key=.*/d" "$edit_file"
}

interaction_cutoff_menu() {
  local edit_file="$1"
  local ans=""
  echo "Select cutoff method after factory reset: "
  echo "(1) shutdown"
  echo "(2) reboot"
  echo "(3) battery cutoff"
  echo "(4) battery cutoff at shutdown"
  echo ""
  echo -n "Please select an option: "
  read ans
  case "$ans" in
    1 )
      replace_or_append "$FLAG_CUTOFF_METHOD" "shutdown" "$edit_file"
      ;;
    2 )
      replace_or_append "$FLAG_CUTOFF_METHOD" "reboot" "$edit_file"
      ;;
    3 )
      replace_or_append "$FLAG_CUTOFF_METHOD" "battery_cutoff" "$edit_file"
      ;;
    4 )
      replace_or_append "$FLAG_CUTOFF_METHOD" "battery_cutoff_at_shutdown" \
        "$edit_file"
      ;;
    * )
      warn "Unknown answer: $ans"
  esac

  # Set up cutoff ac state
  if [ "$ans" -eq 3 ] || [ "$ans" -eq 4 ]; then
    echo "Select cutoff AC state:"
    echo "(1) disconnect AC"
    echo "(2) connect AC"
    echo ""
    echo -n "Please select an option:"
    read ans
    case "$ans" in
      1 )
        replace_or_append "$FLAG_CUTOFF_AC_STATE" "remove_ac" "$edit_file"
        ;;
      2 )
        replace_or_append "$FLAG_CUTOFF_AC_STATE" "connect_ac" "$edit_file"
        ;;
      * )
        warn "Unknown answer: $ans"
    esac
  fi

  echo -n "Minimum allowed battery percentage:" \
    "(Keep empty to bypass checking):"
  read ans
  if [ -z "$ans" ]; then
    remove_flag "$FLAG_CUTOFF_BATTERY_MIN_PERCENTAGE" "$edit_file"
  else
    if [ "$ans" -ge "0" ] && [ "$ans" -le "100" ]; then
      replace_or_append "$FLAG_CUTOFF_BATTERY_MIN_PERCENTAGE" \
        "$ans" "$edit_file"
    else
      warn "Invalid percentage: $ans"
    fi
  fi

  echo -n "Maximum allowed battery percentage:" \
    "(Keep empty to bypass checking):"
  read ans
  if [ -z "$ans" ]; then
    remove_flag "$FLAG_CUTOFF_BATTERY_MAX_PERCENTAGE" "$edit_file"
  else
    if [ "$ans" -ge "0" ] && [ "$ans" -le "100" ]; then
      replace_or_append "$FLAG_CUTOFF_BATTERY_MAX_PERCENTAGE" \
        "$ans" "$edit_file"
    else
      warn "Invalid percentage: $ans"
    fi
  fi

  echo -n "Minimum allowed battery voltage(mA):" \
    "(Keep empty to bypass checking):"
  read ans
  if [ -z "$ans" ]; then
    remove_flag "$FLAG_CUTOFF_BATTERY_MIN_VOLTAGE" "$edit_file"
  else
    replace_or_append "$FLAG_CUTOFF_BATTERY_MIN_VOLTAGE" \
      "$ans" "$edit_file"
  fi

  echo -n "Maximum allowed battery voltage(mA):" \
    "(Keep empty to bypass checking):"
  read ans
  if [ -z "$ans" ]; then
    remove_flag "$FLAG_CUTOFF_BATTERY_MAX_VOLTAGE" "$edit_file"
  else
    replace_or_append "$FLAG_CUTOFF_BATTERY_MAX_VOLTAGE" \
      "$ans" "$edit_file"
  fi

  echo ""
  echo "Shopfloor URL (Keep empty if no need to inform shopfloor after reset):"
  echo "Default XML-RPC request will be sent via HTTP/POST with method"
  echo "'FinalizeFQC' and SN as the parameter."
  read ans
  if [ -z "$ans" ]; then
    remove_flag "$FLAG_SHOPFLOOR_URL" "$edit_file"
  else
    replace_or_append "$FLAG_SHOPFLOOR_URL" "$ans" "$edit_file"
  fi
}

interaction_menu() {
  local src_file="$1"
  local edit_file="$2"
  local ans

  echo ""
  echo "Contents of current $lsb_file:"
  echo "----------------------------------------------------------------------"
  cat "$edit_file"
  echo "----------------------------------------------------------------------"
  echo "(1) Modify mini-Omaha server host."
  echo "(2) Enable/disable board prompt on download."
  echo "(3) Enable/disable RELEASE-ONLY recovery download mode."
  echo "(4) Modify cutoff method after factory reset."
  echo "(5) Enable/disable RMA autorun."
  echo "(w) Write settings and exit."
  echo "(q) Quit without saving."
  echo ""
  echo -n "Please select an option: "
  read choice
  case "$choice" in
    1 )
      local host="$(sed -n 's"^CHROMEOS_DEVSERVER=http://\([^/]*\).*"\1"p' \
                    "$edit_file")"
      echo "- Current mini-Omaha server host address: $host"
      echo -n "Enter new mini-Omaha server host address: "
      read ans
      [ -n "$ans" ] || return $FLAGS_TRUE
      [[ "$ans" == *':'* ]] || ans="${ans}:8080"
      local new_url="http://$ans/update"
      replace_or_append "CHROMEOS_AUSERVER" "$new_url" "$edit_file"
      replace_or_append "CHROMEOS_DEVSERVER" "$new_url" "$edit_file"
      ;;
    2 )
      echo -n "Enable (or 'n' to disable) board prompt? (y/n): "
      read ans
      case "$ans" in
        y )
          replace_or_append "USER_SELECT" "true" "$edit_file"
          ;;
        n )
          replace_or_append "USER_SELECT" "false" "$edit_file"
          ;;
        * )
          warn "Unknown answer: $ans"
      esac
      ;;
    3 )
      echo -n "Enable (or 'n' to disable) RELEASE-ONLY download mode? (y/n): "
      read ans
      case "$ans" in
        y )
          replace_or_append "RELEASE_ONLY" "1" "$edit_file"
          ;;
        n )
          replace_or_append "RELEASE_ONLY" "" "$edit_file"
          ;;
        * )
          warn "Unknown answer: $ans"
      esac
      ;;
    4 )
      interaction_cutoff_menu "$edit_file"
      ;;
    5 )
      echo -n "Enable (or 'n' to disable) RMA autorun? (y/n): "
      read ans
      case "$ans" in
        y )
          replace_or_append "RMA_AUTORUN" "true" "$edit_file"
          ;;
        n )
          replace_or_append "RMA_AUTORUN" "false" "$edit_file"
          ;;
        * )
          warn "Unknown answer: $ans"
      esac
      ;;
    w )
      # Make a backup of current (before modification) lsb-factor file so people
      # can track what has been changed, and if anything has broken.
      sudo cp -pf "$src_file" "${src_file}.bak.$(date +'%Y%m%d%H%M')" || true
      sudo cp -f "$edit_file" "$src_file" || die "Failed to modify file."
      sudo chown root "$src_file"
      sudo chmod a+r,u+w,go-w,a-x "$src_file"
      info "Successfully Modified $image"
      return $FLAGS_FALSE
      ;;
    q )
      warn "lsb-factory file is NOT modified. All modifications abandoned."
      return $FLAGS_ERROR
      ;;
    * )
      warn "Unknown selection: $choice"
      ;;
  esac
  return $FLAGS_TRUE
}

# Edits lsb-factory in disk image file.
edit_lsb_factory() {
  local image="$(readlink -f "$1")"
  local temp_mount="$(mktemp -d --tmpdir)"
  local edit_file="$(mktemp --tmpdir)"
  local lsb_file="/dev_image/etc/lsb-factory"
  local src_file="$temp_mount$lsb_file"
  image_add_temp "$temp_mount" "$edit_file"

  image_mount_partition "$image" "1" "$temp_mount" "rw" "" ||
    die "Cannot mount partition #1 (stateful) in disk image: $image"
  [ -f "$src_file" ] ||
    die "No $lsb_file file in disk image: $image . " \
        "Please make sure you've specified a factor installer image."
  sudo cat "$src_file" >"$edit_file"

  while interaction_menu "$src_file" "$edit_file"; do
    true
  done

  image_umount_partition "$temp_mount"
}

main() {
  set -e
  trap on_exit EXIT
  if [ "$#" != 0 ]; then
    flags_help
    exit 1
  fi

  # TODO(hungte) Handle block device files
  check_parameters
  image_check_part_tools

  edit_lsb_factory "$FLAGS_image"
}

main "$@"
