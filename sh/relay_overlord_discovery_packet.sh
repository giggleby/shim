#!/bin/sh
#
# Copyright 2015 The Chromium OS Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.
#
# This script relays Overlord LAN discovery packets to a interface
#

. "$(dirname "$(readlink -f "$0")")/common.sh" || exit 1

QUIT=false

clean_up() {
  QUIT=true
  pkill -9 -P $$
}

get_broadcast_ip() {
  local iface="$1"
  echo "$(ifconfig $iface | awk '/broadcast/ { print $6 }')"
}

main() {
  if [ "$#" -ne "1" ]; then
    alert "ERROR: Usage: $0 interface"
    exit 1
  fi

  local bcast_ip="$(get_broadcast_ip "$1")"
  if [ -z "${bcast_ip}" ]; then
    die "Can not find interface $1"
  fi

  while true; do
    socat -u UDP-RECVFROM:4456 UDP-DATAGRAM:${bcast_ip}:4456,broadcast
    if ${QUIT}; then
      break
    fi
    sleep 1
  done
}

trap clean_up EXIT INT

main "$@"
