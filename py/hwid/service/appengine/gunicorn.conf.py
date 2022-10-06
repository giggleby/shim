# Copyright 2020 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.
"""gunicorn settings."""

import multiprocessing

workers = multiprocessing.cpu_count() * 2 + 1
threads = 1
