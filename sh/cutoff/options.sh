#!/bin/sh
# Copyright 2016 The Chromium OS Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

# Reads `options` file and check parameters for cut-off scripts.

# Define config default values
: ${CUTOFF_METHOD:=shutdown}
: ${CUTOFF_AC_STATE:=}
: ${CUTOFF_BATTERY_MIN_PERCENTAGE:=}
: ${CUTOFF_BATTERY_MAX_PERCENTAGE:=}
: ${CUTOFF_BATTERY_MIN_VOLTAGE:=}
: ${CUTOFF_BATTERY_MAX_VOLTAGE:=}
: ${SHOPFLOOR_URL:=}

# After calling display_wipe_message.sh to draw image with frecon, we must
# redirect text output to tty1 to display information on the screen.
: ${TTY:=/dev/tty1}

# Exit as error with messages.
# Usage: die messages...
die() {
  echo "ERROR: $*" >&2
  exit 1
}

# Try to read from config file. This file should be using same format that
# /etc/lsb-release is using and friendly for sh to process.
# TODO(hungte) Load options in a safer way.
# Usage: load_options_file <FILE>
options_load_file() {
  local file="$1"
  if [ -f "${file}" ]; then
    echo "Loading options from file ${file}..."
    . "${file}"
  fi
}

# Check if an option in number type.
# Usage: option_check_range <value> <value_name> <range-min> <range-max>
option_check_range() {
  local value="$1"
  local value_name="$2"
  local value_min="$3"
  local value_max="$4"
  if [ -z "${value}" ]; then
    return 0
  fi
  if [ "${value}" -ge "${value_min}" -a "${value}" -le "${value_max}" ]; then
    return 0
  fi
  die "Option ${value_name} not in range [${value_min},${value_max}]: ${value}"
}

# Check if an option is in known set.
# Usage: option_check_set <value> <value_name> <valid_values...>
option_check_set() {
  local value="$1"
  local value_name="$2"
  shift
  shift
  local valid_values="$*"
  if [ -z "${value}" ]; then
    return 0
  fi
  while [ "$#" -gt 0 ]; do
    if [ "${value}" = "$1" ]; then
      return 0
    fi
    shift
  done
  die "Option ${value_name} is not one of [${valid_values}]: ${valud}"
}

# Checks known option values.
# Usage: options_check_values
options_check_values() {
  option_check_set "${CUTOFF_METHOD}" CUTOFF_METHOD \
    shutdown reboot battery_cutoff ectool_cutoff
  option_check_set "${CUTOFF_AC_STATE}" CUTOFF_AC_STATE \
    connect_ac remove_ac
  option_check_range "${CUTOFF_BATTERY_MIN_PERCENTAGE}" \
    CUTOFF_BATTERY_MIN_PERCENTAGE 0 100
  option_check_range "${CUTOFF_BATTERY_MAX_PERCENTAGE}" \
    CUTOFF_BATTERY_MAX_PERCENTAGE 0 100
  if [ ! -e "${TTY}" ]; then
    die "Cannot find valid TTY in ${TTY}."
  fi
  echo "Active Configuration:"
  echo "---------------------"
  echo "CUTOFF_METHOD=${CUTOFF_METHOD}"
  echo "CUTOFF_AC_STATE=${CUTOFF_AC_STATE}"
  echo "CUTOFF_BATTERY_MIN_PERCENTAGE=${CUTOFF_BATTERY_MIN_PERCENTAGE}"
  echo "CUTOFF_BATTERY_MAX_PERCENTAGE=${CUTOFF_BATTERY_MAX_PERCENTAGE}"
  echo "CUTOFF_BATTERY_MIN_VOLTAGE=${CUTOFF_BATTERY_MIN_VOLTAGE}"
  echo "CUTOFF_BATTERY_MAX_VOLTAGE=${CUTOFF_BATTERY_MAX_VOLTAGE}"
  echo "SHOPFLOOR_URL=${SHOPFLOOR_URL}"
  echo "TTY=${TTY}"
  echo "---------------------"
}

# Provides common usage help.
# Usage: options_usage_help
options_usage_help() {
  echo "Usage: $0
    [--method shutdown|reboot|battery_cutoff|ectool_cutoff]
    [--check-ac connect_ac|remove_ac]
    [--min-battery-percent <minimum battery percentage>]
    [--max-battery-percent <maximum battery percentage>]
    [--min-battery-voltage <minimum battery voltage>]
    [--max-battery-voltage <maximum battery voltage>]
    [--shopfloor <shopfloor_url]
    [--tty <tty_path>]
    "
  exit 1
}

# Parses options from command line.
# Usage: options_parse_command_line "$@"
options_parse_command_line() {
  while [ "$#" -ge 1 ]; do
    case "$1" in
      --method )
        shift
        CUTOFF_METHOD="$1"
        ;;
      --check-ac )
        shift
        CUTOFF_AC_STATE="$1"
        ;;
      --min-battery-percent )
        shift
        CUTOFF_BATTERY_MIN_PERCENTAGE="$1"
        ;;
      --max-battery-percent )
        shift
        CUTOFF_BATTERY_MAX_PERCENTAGE="$1"
        ;;
      --min-battery-voltage )
        shift
        CUTOFF_BATTERY_MIN_VOLTAGE="$1"
        ;;
      --max-battery-voltage )
        shift
        CUTOFF_BATTERY_MAX_VOLTAGE="$1"
        ;;
      --shopfloor )
        shift
        SHOPFLOOR_URL="$1"
        ;;
      --tty )
        shift
        TTY="$1"
        ;;
      * )
        options_usage_help "$1"
        ;;
    esac
    shift
  done
}

# Always load default config file.
options_load_file "$(dirname $(readlink -f "$0"))/cutoff.conf"
options_load_file "/mnt/stateful_partition/dev_image/etc/lsb-factory"
