#!/usr/bin/env python3
# Copyright 2018 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Tests for memcache_adapter."""

import pickle
import time
from typing import Mapping
import unittest
from unittest import mock

import redis

from cros.factory.hwid.service.appengine import memcache_adapter


class MemcacheAdapterTest(unittest.TestCase):

  def setUp(self):
    super().setUp()
    memcache_adapter.MEMCACHE_CHUNKSIZE = 950000
    memcache_adapter.MAX_NUMBER_CHUNKS = 10
    self._memadapter = memcache_adapter.MemcacheAdapter('testnamespace')

  def tearDown(self):
    super().tearDown()
    self._memadapter.ClearAll()

  def testBreakIntoChunks(self):
    memcache_adapter.MEMCACHE_CHUNKSIZE = 2
    serialized_data = b'aabb'
    chunks = self._memadapter.BreakIntoChunks('testkey', serialized_data)

    self.assertEqual(2, len(chunks))
    self.assertEqual(b'aa', chunks['testnamespace.py3:testkey.0'])
    self.assertEqual(b'bb', chunks['testnamespace.py3:testkey.1'])

  def testBreakIntoChunksNone(self):
    memcache_adapter.MEMCACHE_CHUNKSIZE = 2
    serialized_data = ''
    chunks = self._memadapter.BreakIntoChunks('testkey', serialized_data)

    self.assertEqual(0, len(chunks))

  @mock.patch.object(redis.Redis, 'mset')
  @mock.patch.object(pickle, 'dumps', return_value=b'aabb')
  def testPut(self, mock_pickle, mock_redis_mset):
    memcache_adapter.MEMCACHE_CHUNKSIZE = 4
    data = ['aa', 'bb']

    self._memadapter.Put('testkey', data)

    mock_redis_mset.assert_called_once_with({
        'testnamespace.py3:testkey.0': b'aabb'})
    mock_pickle.assert_called_once_with(
        ['aa', 'bb'], memcache_adapter.PICKLE_PROTOCOL_VERSION)

  def testPutTooBig(self):
    memcache_adapter.MEMCACHE_CHUNKSIZE = 4
    memcache_adapter.MAX_NUMBER_CHUNKS = 2
    data = ['aa', 'bb']

    self.assertRaises(memcache_adapter.MemcacheAdapterException,
                      self._memadapter.Put, 'testkey', data)

  @mock.patch.object(redis.Redis, 'mget',
                     return_value=[b'yy', b'zz'])
  @mock.patch.object(pickle, 'loads', return_value='pickle_return')
  def testGet(self, mock_pickle, mock_redis_mget):
    memcache_adapter.MAX_NUMBER_CHUNKS = 2

    value = self._memadapter.Get('testkey')

    mock_redis_mget.assert_called_once_with(['testnamespace.py3:testkey.0',
                                             'testnamespace.py3:testkey.1'])
    mock_pickle.assert_called_once_with(b'yyzz')
    self.assertEqual('pickle_return', value)

  @mock.patch.object(redis.Redis, 'mset')
  @mock.patch.object(redis.Redis, 'mget')
  def testEnd2End(self, mock_redis_mget, mock_redis_mset):
    object_to_save = ['one', 'two', 'three']
    memcache_adapter.MEMCACHE_CHUNKSIZE = 8

    self._memadapter.Put('testkey', object_to_save)
    arg = mock_redis_mset.call_args[0][0]

    # Return values sorted by key
    mock_redis_mget.return_value = list(map(arg.get, sorted(arg)))
    retrieved_object = self._memadapter.Get('testkey')

    self.assertListEqual(object_to_save, retrieved_object)

  def testExpiry(self):
    object_to_save = {
        'a': 1,
        'b': 2,
        'c': 3
    }

    self._memadapter.Put('testkey-noexpire', object_to_save)
    self._memadapter.Put('testkey-expire', object_to_save, expiry=1)

    retrived_no_expire_before_sleep = self._memadapter.Get('testkey-noexpire')
    retrived_expire_before_sleep = self._memadapter.Get('testkey-expire')

    self.assertDictEqual(object_to_save, retrived_no_expire_before_sleep)
    self.assertDictEqual(object_to_save, retrived_expire_before_sleep)

    time.sleep(2)

    retrived_no_expire_after_sleep = self._memadapter.Get('testkey-noexpire')
    retrived_expire_after_sleep = self._memadapter.Get('testkey-expire')

    self.assertDictEqual(object_to_save, retrived_no_expire_after_sleep)
    self.assertIsNone(retrived_expire_after_sleep)

  def testDelByPattern(self):
    existent_data = {
        'a1': b'a1data',
        'a2': b'a2data',
        'b1': b'b1data',
        'b2': b'b2data',
    }
    self._FillValue(existent_data)

    self._memadapter.DelByPattern('a*')
    remaining_data = {key: self._memadapter.Get(key)
                      for key in existent_data}

    self.assertDictEqual(
        {
            'a1': None,
            'a2': None,
            'b1': b'b1data',
            'b2': b'b2data',
        }, remaining_data)

  def testSetAddGetOperations_Integers(self):
    # Act.  Firstly add some data to the memcache adapter.
    self._memadapter.AddToSet('key1', {1, 2, 3, 4, 5})
    self._memadapter.AddToSet('key2', {3, 4, '5', b'6', 7})

    # Then get the data back in integer set type.
    actual_key1_value = self._memadapter.GetIntSetElements('key1')
    actual_key2_value = self._memadapter.GetIntSetElements('key2')

    # Assert.  The retrieved data as integers are expected.
    self.assertCountEqual(actual_key1_value, {1, 2, 3, 4, 5})
    self.assertCountEqual(actual_key2_value, {3, 4, 5, 6, 7})

  def testSetAddGetOperations_NonIntegers(self):
    key = 'key'
    self._memadapter.AddToSet(key, {1, 2, 3, 4, 'NaN'})

    self.assertRaises(memcache_adapter.MemcacheAdapterException,
                      self._memadapter.GetIntSetElements, key)

  def testSetAddGetOperations_Strings(self):
    # Act.  Firstly add some data to the memcache adapter.
    self._memadapter.AddToSet('key1', {1, 2, 3})
    self._memadapter.AddToSet('key2', {'str1', 'str2'})

    # Then get the data back in string set type.
    actual_key1_value = self._memadapter.GetStrSetElements('key1')
    actual_key2_value = self._memadapter.GetStrSetElements('key2')

    # Assert.  The retrieved data as strings are expected.
    self.assertCountEqual({'1', '2', '3'}, actual_key1_value)
    self.assertCountEqual({'str1', 'str2'}, actual_key2_value)

  def testSetAddGetOperations_InvalidStrings(self):
    key = 'key'
    values = {'str1', 'str2', b'\xff\xff\xff'}
    self._memadapter.AddToSet(key, values)

    self.assertRaises(memcache_adapter.MemcacheAdapterException,
                      self._memadapter.GetStrSetElements, key)

  def testRemoveFromSet(self):
    self._memadapter.AddToSet('key', {b'a', b'b', b'c', b'd'})

    remove_existent = self._memadapter.RemoveFromSet('key', b'a')
    remove_non_existent = self._memadapter.RemoveFromSet('key', b'e')
    remaining = self._memadapter.GetBytesSetElements('key')

    self.assertTrue(remove_existent)
    self.assertFalse(remove_non_existent)
    self.assertCountEqual({b'b', b'c', b'd'}, remaining)

  def testClearSet(self):
    existent_sets = {
        'key1': {b'a', b'b', b'c', b'd'},
        'key2': {b'c', b'd', b'e', b'f'},
    }
    for key, val in existent_sets.items():
      self._memadapter.AddToSet(key, val)

    self._memadapter.ClearSet('key1')

    self.assertFalse(self._memadapter.GetBytesSetElements('key1'))
    self.assertTrue(self._memadapter.GetBytesSetElements('key2'))

  def _FillValue(self, data: Mapping[str, bytes]):
    for key, val in data.items():
      self._memadapter.Put(key, val)


if __name__ == '__main__':
  unittest.main()
