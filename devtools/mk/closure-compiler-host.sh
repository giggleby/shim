#!/bin/bash
# Copyright 2023 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

# This file is modified from /opt/bin/closure-compiler installed by
# dev-lang/closure-compiler-bin. We add `ROOT=` here to invoke the java from
# host. If we don't do this, then the `ROOT`` will be set to /build/${BOARD} and
# prevent builders to find the closure-compiler-bin.

export gjl_package=closure-compiler-bin
export gjl_jar="/opt/closure-compiler-bin-0/lib/closure-compiler-bin.jar"
export ROOT=
source /usr/share/java-config-2/launcher/launcher.bash
