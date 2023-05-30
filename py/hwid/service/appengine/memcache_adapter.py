# Copyright 2018 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""A connector to memcache that deals with the 1M data size limitiation."""

import logging
import os
import pickle
from typing import Collection, Optional, Union

import redis


PICKLE_PROTOCOL_VERSION = 2
MAX_NUMBER_CHUNKS = 10
# Chunksize has to be less than 1000000 bytes which is the max size for a
# memcache data entry.  Tweaking this number may improve/reduce performance.
MEMCACHE_CHUNKSIZE = 950000
_REDIS_VALUE_TYPES_TO_SET = Union[bytes, memoryview, str, int, float]


class MemcacheAdapterException(Exception):
  pass


class MemcacheAdapter:
  """Memcache connector that can store objects larger than 1M.

  This connector will save items to the memcache by first serializing the object
  then breaking that serialized data up into chunks that are small enough to
  fit into memcache.

  You should not use this connector unless you are sure your data may be
  greater than 1M, breaking up the data adds a performance overhead.
  """

  def __init__(self, namespace=None):
    self.namespace = namespace
    redis_host = os.environ.get('REDIS_HOST', 'localhost')
    redis_port = int(os.environ.get('REDIS_PORT', 6379))
    self.client = redis.Redis(host=redis_host, port=redis_port,
                              health_check_interval=30)

  def ClearAll(self):
    """Clear all items in cache.

    This method is for testing purpose since each integration test should have
    empty cache in the beginning.
    """
    self.client.flushall()

  def _KeyWithNamespace(self, key: str, chunk_id: Optional[int] = None) -> str:
    if chunk_id is None:
      return f'{self.namespace}.py3:{key}'
    return f'{self.namespace}.py3:{key}.{chunk_id}'

  def BreakIntoChunks(self, key, serialized_data):
    chunks = {}
    # Split serialized object into chunks no bigger than chunksize. The unique
    # key for the split chunks is <key>.<number> so the first chunk for key SNOW
    # will be SNOW.0 the second chunk will be in SNOW.1
    for i in range(0, len(serialized_data), MEMCACHE_CHUNKSIZE):
      chunk_key = self._KeyWithNamespace(key, i // MEMCACHE_CHUNKSIZE)
      chunks[chunk_key] = serialized_data[i : i+MEMCACHE_CHUNKSIZE]
    return chunks

  def Put(self, key, value, expiry: Optional[int] = None):
    """Store an object too large to fit directly into memcache."""
    serialized_value = pickle.dumps(value, PICKLE_PROTOCOL_VERSION)

    chunks = self.BreakIntoChunks(key, serialized_value)
    if len(chunks) > MAX_NUMBER_CHUNKS:
      raise MemcacheAdapterException('Object too large to store in memcache.')

    logging.debug('Memcache writing %s', key)
    self.client.mset(chunks)
    if expiry is not None:
      for chunk_key in chunks:
        self.client.expire(chunk_key, expiry)

  def Get(self, key):
    """Retrieve and re-assemble a large object from memcache."""
    keys = [self._KeyWithNamespace(key, i) for i in range(MAX_NUMBER_CHUNKS)]
    chunks = self.client.mget(keys)
    serialized_data = b''.join(filter(None, chunks))
    if not serialized_data:
      logging.debug('Memcache no data found %s', key)
      return None
    try:
      return pickle.loads(serialized_data)
    except (TypeError, pickle.UnpicklingError) as ex:
      logging.debug('Memcache load fail (%r), treat it as cache expired.', ex)
      return None

  def DelByPattern(self, entry_key_pattern: str):
    """Deletes entries by the given pattern.

    Args:
      entry_key_pattern: The pattern of keys to delete.
    """

    keys = self.client.keys(self._KeyWithNamespace(entry_key_pattern))
    if keys:
      self.client.delete(*keys)

  def AddToSet(self, key: str, values: Collection[_REDIS_VALUE_TYPES_TO_SET]):
    """Adds elements to a set identified by a key.

    Args:
      key: The key of the set.
      values: A collections of acceptable data types which will be encoded to
          bytes in memcache.
    """
    self.client.sadd(self._KeyWithNamespace(key), *values)

  def GetIntSetElements(self, key: str) -> Collection[int]:
    """Gets the set elements of integers identified by the key.

    Args:
      key: The key of the set.

    Returns:
      The collection of the integer set elements identified by the key.

    Raises:
      MemcacheAdapterException: Raised if the set contains non-integer data.
    """
    try:
      return {
          int(x)
          for x in self.client.smembers(self._KeyWithNamespace(key))
      }
    except ValueError:
      raise MemcacheAdapterException(
          'The set element is not an integer.') from None

  def GetStrSetElements(self, key: str, encoding='utf8') -> Collection[str]:
    """Gets the set elements of strings identified by the key.

    Args:
      key: The key of the set.
      encoding: The encoding of the string which will be used to decode the
          bytes of set elements in memcache.

    Returns:
      The collection of the string set elements identified by the key.

    Raises:
      MemcacheAdapterException: Raised if the set contains data cannot be
          decoded by the encoding.
    """
    try:
      return {
          x.decode(encoding)
          for x in self.client.smembers(self._KeyWithNamespace(key))
      }
    except UnicodeDecodeError:
      raise MemcacheAdapterException(
          f'A set element cannot be decoded by the encoding {encoding!r}.'
      ) from None

  def GetBytesSetElements(self, key: str) -> Collection[bytes]:
    """Gets the set elements of bytes identified by the key.

    Args:
      key: The key of the set.

    Returns:
      The collection of the set elements identified by the key.
    """
    return self.client.smembers(self._KeyWithNamespace(key))

  def RemoveFromSet(self, key: str, value: _REDIS_VALUE_TYPES_TO_SET) -> bool:
    """Removes one element from a set.

    Args:
      key: The key of the set.
      value: The element to remove.

    Returns:
      A bool indicating whether the value is found and removed.
    """
    return bool(self.client.srem(self._KeyWithNamespace(key), value))

  def ClearSet(self, key: str):
    """Clears a set by a key.

    Args:
      key: The key of the set.
    """
    self.client.delete(self._KeyWithNamespace(key))
