# Copyright 2021 The Chromium OS Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.
"""Provides an interface to access / use Google Cloud NDB."""

from google.cloud import ndb

from cros.factory.utils import type_utils


class NDBConnector:

  @type_utils.LazyProperty
  def _ndb_client(self):
    return ndb.Client()

  @type_utils.LazyProperty
  def _global_cache(self):
    return ndb.RedisCache.from_environment()

  def CreateClientContextWithGlobalCache(self):
    return self._ndb_client.context(global_cache=self._global_cache)

  def CreateClientContext(self):
    return self._ndb_client.context()
