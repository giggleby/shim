#!/bin/bash
#
# Copyright 2015 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

INCREMENT=42
n=$RANDOM
echo "TEST-SHELL-CHALLENGE $n"
read input
[[ "$input" == "$(expr $n + $INCREMENT)" ]] && echo 'SUCCESS' || echo 'FAILED'
