#!/usr/bin/env python
# Copyright (c) 2014 The Chromium OS Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Uploader related exceptions."""


class UploaderError(Exception):
  pass


class UploaderFieldError(UploaderError):
  pass


class UploaderConnectionError(UploaderError):
  pass
