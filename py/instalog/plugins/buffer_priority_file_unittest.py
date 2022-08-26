#!/usr/bin/env python3
#
# Copyright 2017 The Chromium OS Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Unittests for priority multi-file-based buffer."""

import copy
import logging
import random
import shutil
import tempfile
import threading
import unittest

import psutil

from cros.factory.instalog import datatypes
from cros.factory.instalog import log_utils
from cros.factory.instalog.plugins import buffer_priority_file
from cros.factory.instalog.utils import file_utils
from cros.factory.unittest_utils import label_utils


_TEST_PRODUCER = 'test_producer'


# pylint: disable=protected-access
# TODO (b/205776055)
@label_utils.Informational
class TestBufferPriorityFile(unittest.TestCase):

  def _CreateBuffer(self, config=None):
    # Remove previous temporary folder if any.
    if self.data_dir is not None:
      shutil.rmtree(self.data_dir)
    self.data_dir = tempfile.mkdtemp(prefix='buffer_priority_file_unittest_')
    logging.info('Create state directory: %s', self.data_dir)
    self.sf = buffer_priority_file.BufferPriorityFile(
        config={} if config is None else config,
        logger_name='priority_file',
        store={},
        plugin_api=None)
    self.sf.GetDataDir = lambda: self.data_dir
    self.sf.SetUp()

  def setUp(self):
    self.data_dir = None
    self._CreateBuffer()

    self.pri_level_max = buffer_priority_file._PRIORITY_LEVEL
    self.e = []
    for pri_level in range(self.pri_level_max):
      self.e.append(datatypes.Event({'priority': pri_level}))
    self.non_consumable_file = []
    for pri_level in range(self.pri_level_max):
      mgr = self.sf.non_consumable_events_mgrs[pri_level]
      self.non_consumable_file.append(mgr.GetNonConsumableFile(_TEST_PRODUCER))

  def tearDown(self):
    shutil.rmtree(self.data_dir)

  def _ProducePriorityEvent(self, pri_level, target_file_num=None,
                            consumable=True, producer=_TEST_PRODUCER):
    """Produces a priority event to a specific data buffer."""
    assert pri_level < self.pri_level_max
    if target_file_num is not None:
      for file_num, file_num_lock in enumerate(self.sf._file_num_lock):
        if file_num != target_file_num:
          file_num_lock.acquire()
    result = self.sf.Produce(producer, [copy.deepcopy(self.e[pri_level])],
                             consumable)
    assert result, 'Emit failed!'
    if target_file_num is not None:
      for file_num, file_num_lock in enumerate(self.sf._file_num_lock):
        if file_num != target_file_num:
          file_num_lock.release()

  def testConsumeOrder(self):
    self.sf.AddConsumer('a')

    self._ProducePriorityEvent(0, 0)
    self._ProducePriorityEvent(1, 1)
    self._ProducePriorityEvent(2, 2)
    self._ProducePriorityEvent(3, 3)
    stream = self.sf.Consume('a')
    for pri_level in range(self.pri_level_max):
      self.assertEqual(self.e[pri_level], stream.Next())
    self.assertEqual(None, stream.Next())
    stream.Commit()

    self._ProducePriorityEvent(3, 3)
    self._ProducePriorityEvent(2, 2)
    self._ProducePriorityEvent(1, 1)
    self._ProducePriorityEvent(0, 0)
    stream = self.sf.Consume('a')
    for pri_level in range(self.pri_level_max):
      self.assertEqual(self.e[pri_level], stream.Next())
    self.assertEqual(None, stream.Next())
    stream.Commit()

    self._ProducePriorityEvent(3, 0)
    self._ProducePriorityEvent(2, 0)
    self._ProducePriorityEvent(1, 0)
    self._ProducePriorityEvent(0, 0)
    stream = self.sf.Consume('a')
    for pri_level in range(self.pri_level_max):
      self.assertEqual(self.e[pri_level], stream.Next())
    self.assertEqual(None, stream.Next())
    stream.Commit()

    self._ProducePriorityEvent(0)
    self._ProducePriorityEvent(3)
    stream = self.sf.Consume('a')
    self.assertEqual(self.e[0], stream.Next())
    self.assertEqual(self.e[3], stream.Next())
    self._ProducePriorityEvent(2)
    self._ProducePriorityEvent(0)
    self.assertEqual(self.e[0], stream.Next())
    self.assertEqual(self.e[2], stream.Next())
    self.assertEqual(None, stream.Next())
    stream.Commit()

  def testMultithreadOrder(self):
    self.sf.AddConsumer('a')
    stream = self.sf.Consume('a')

    events = []
    for _unused_i in range(2000):
      for pri_level in range(self.pri_level_max):
        events.append(self.e[pri_level])
    random.shuffle(events)
    threads = []
    for i in range(0, 2000 * self.pri_level_max, 1000):
      threads.append(
          threading.Thread(target=self.sf.Produce,
                           args=(_TEST_PRODUCER, events[i:i + 1000], True)))
    for t in threads:
      t.start()
    for t in threads:
      t.join()

    for pri_level in range(self.pri_level_max):
      for i in range(2000):
        self.assertEqual(self.e[pri_level], stream.Next())
    self.assertEqual(None, stream.Next())

  def testTruncate(self):
    self.sf.AddConsumer('a')

    self._ProducePriorityEvent(0, 0)
    self._ProducePriorityEvent(1, 1)
    self._ProducePriorityEvent(2, 2)
    self._ProducePriorityEvent(3, 3)
    self._ProducePriorityEvent(0, 3)
    self._ProducePriorityEvent(1, 2)
    self._ProducePriorityEvent(2, 1)
    self._ProducePriorityEvent(3, 0)

    stream = self.sf.Consume('a')
    self.assertEqual(self.e[0], stream.Next())
    self.assertEqual(self.e[0], stream.Next())
    self.assertEqual(self.e[1], stream.Next())
    stream.Commit()

    self.sf.Truncate()
    stream = self.sf.Consume('a')
    self.assertEqual(self.e[1], stream.Next())
    self.assertEqual(self.e[2], stream.Next())
    stream.Commit()

    self._ProducePriorityEvent(0)
    self._ProducePriorityEvent(1)

    stream = self.sf.Consume('a')
    self.assertEqual(self.e[0], stream.Next())
    self.assertEqual(self.e[1], stream.Next())
    self.assertEqual(self.e[2], stream.Next())
    stream.Commit()

    self._ProducePriorityEvent(0)
    self._ProducePriorityEvent(1)

    self.sf.Truncate()
    self.sf.TearDown()
    self.sf.SetUp()

    stream = self.sf.Consume('a')
    self.assertEqual(self.e[0], stream.Next())
    self.assertEqual(self.e[1], stream.Next())
    self.assertEqual(self.e[3], stream.Next())
    stream.Commit()

    self._ProducePriorityEvent(0)
    self._ProducePriorityEvent(1)

    stream = self.sf.Consume('a')
    self.assertEqual(self.e[0], stream.Next())
    self.assertEqual(self.e[1], stream.Next())
    self.assertEqual(self.e[3], stream.Next())
    self.assertEqual(None, stream.Next())
    stream.Commit()

  def testTruncateWithAttachments(self):
    self._CreateBuffer({'copy_attachments': True})
    for pri_level in range(self.pri_level_max):
      path = file_utils.CreateTemporaryFile()
      file_utils.WriteFile(path, 'Priority leve = %d' % pri_level)
      self.e[pri_level].attachments['att'] = path
    self.testTruncate()

  def testRecoverTemporaryMetadata(self):
    self.sf.AddConsumer('a')
    stream = self.sf.Consume('a')

    self._ProducePriorityEvent(0, 0)
    self._ProducePriorityEvent(1, 1)
    self._ProducePriorityEvent(2, 2)
    self._ProducePriorityEvent(3, 3)

    self.assertEqual(self.e[0], stream.Next())

    self.sf.SaveTemporaryMetadata(0)
    # These four events should be ignored.
    self._ProducePriorityEvent(0, 0)
    self._ProducePriorityEvent(0, 0)
    self._ProducePriorityEvent(0, 0)
    self._ProducePriorityEvent(0, 0)
    # These two events should be recorded.
    self._ProducePriorityEvent(1, 1)
    self._ProducePriorityEvent(2, 2)

    stream.Commit()
    self.sf.TearDown()
    # SetUp will find the temporary metadata, and recovering it.
    self.sf.SetUp()
    stream = self.sf.Consume('a')

    self._ProducePriorityEvent(3, 3)

    self.assertEqual(self.e[1], stream.Next())
    self.assertEqual(self.e[1], stream.Next())
    self.assertEqual(self.e[2], stream.Next())
    self.assertEqual(self.e[2], stream.Next())
    self.assertEqual(self.e[3], stream.Next())
    self.assertEqual(self.e[3], stream.Next())
    self.assertEqual(None, stream.Next())

  def testRecoverTemporaryMetadataWithAttachments(self):
    self._CreateBuffer({'copy_attachments': True})
    for pri_level in range(self.pri_level_max):
      path = file_utils.CreateTemporaryFile()
      file_utils.WriteFile(path, 'Priority leve = %d' % pri_level)
      self.e[pri_level].attachments['att'] = path
    self.testRecoverTemporaryMetadata()

  def testProduceNonConsumableEvents(self):
    self._ProducePriorityEvent(0, 0, consumable=False)
    self.sf.AddConsumer('a')
    stream = self.sf.Consume('a')
    self.assertEqual(None, stream.Next())

  def testNonConsumableEventsInPreEmitFile(self):
    for produce_pri in range(self.pri_level_max):
      self._ProducePriorityEvent(produce_pri, produce_pri, consumable=False)
      for check_pri in range(self.pri_level_max):
        # MoveFile() will clean up the preemit file after this with statement.
        with self.non_consumable_file[check_pri].MoveFile() as pre_file:
          if produce_pri == check_pri:
            event = datatypes.Event.Deserialize(file_utils.ReadFile(pre_file))
            self.assertEqual(self.e[produce_pri], event)
          else:
            self.assertFalse(file_utils.ReadFile(pre_file))

  def testProduceNonConsumableEventsWithPriority(self):
    self.sf.AddConsumer('a')

    self._ProducePriorityEvent(0, 0, False)
    self._ProducePriorityEvent(1, 1, False)
    self._ProducePriorityEvent(2, 2, False)
    self._ProducePriorityEvent(3, 3)
    stream = self.sf.Consume('a')
    for pri_level in range(self.pri_level_max):
      self.assertEqual(self.e[pri_level], stream.Next())
    self.assertEqual(None, stream.Next())
    stream.Commit()

    self._ProducePriorityEvent(3, 3, False)
    self._ProducePriorityEvent(2, 2, False)
    self._ProducePriorityEvent(1, 1, False)
    self._ProducePriorityEvent(0, 0)
    stream = self.sf.Consume('a')
    for pri_level in range(self.pri_level_max):
      self.assertEqual(self.e[pri_level], stream.Next())
    self.assertEqual(None, stream.Next())
    stream.Commit()

  def testProduceConsumableEventsAfterNonConsumable(self):
    self._ProducePriorityEvent(0, 0, consumable=False)
    self._ProducePriorityEvent(1, 1)
    self.sf.AddConsumer('a')
    stream = self.sf.Consume('a')
    self.assertEqual(self.e[0], stream.Next())
    self.assertEqual(self.e[1], stream.Next())
    self.assertEqual(None, stream.Next())

  def testProduceConsumableEventsMultipleTimesAfterNonConsumable(self):
    self._ProducePriorityEvent(0, 0, consumable=False)
    self._ProducePriorityEvent(1, 1)
    self._ProducePriorityEvent(2, 2)
    self._ProducePriorityEvent(3, 3)
    self.sf.AddConsumer('a')
    stream = self.sf.Consume('a')
    for pri_level in range(self.pri_level_max):
      self.assertEqual(self.e[pri_level], stream.Next())
    self.assertEqual(None, stream.Next())

  def testRestartDropNonConsumableEvents(self):
    self._ProducePriorityEvent(0, 0, consumable=False)
    self.sf.SetUp()
    self._ProducePriorityEvent(1, 1)
    self.sf.AddConsumer('a')
    stream = self.sf.Consume('a')
    self.assertEqual(self.e[1], stream.Next())
    self.assertEqual(None, stream.Next())

  def testProduceNonConsumableEventsWithDifferentProducer(self):
    alt_producer = _TEST_PRODUCER + '_alt'
    self._ProducePriorityEvent(0, 0, consumable=False)
    self._ProducePriorityEvent(0, 0, consumable=False, producer=alt_producer)
    self._ProducePriorityEvent(1, 1)
    self.sf.AddConsumer('a')
    stream = self.sf.Consume('a')
    self.assertEqual(self.e[0], stream.Next())
    self.assertEqual(self.e[1], stream.Next())
    self.assertEqual(None, stream.Next())

    self._ProducePriorityEvent(1, 1, producer=alt_producer)
    self.assertEqual(self.e[0], stream.Next())
    self.assertEqual(self.e[1], stream.Next())
    self.assertEqual(None, stream.Next())

  def testNonConsumableEventsMemoryUsage(self):
    PASS_CRITERIA_DIVIDER = 10
    EVENT_NUM = 500
    # Count virtual memory as we care about the total memory used by objects,
    # not the occupied size on the physical memory.
    memory_before_creating_events = psutil.Process().memory_info().vms
    events = [
        datatypes.Event({
            'test1': 'event',
            'priority': 0
        }) for unused_i in range(EVENT_NUM)
    ]
    memory_after_creating_events = psutil.Process().memory_info().vms
    del events
    rough_memory_for_events = \
        memory_after_creating_events - memory_before_creating_events

    memory_before_produce = psutil.Process().memory_info().vms
    for unused_i in range(EVENT_NUM):
      self.sf.Produce(_TEST_PRODUCER,
                      [datatypes.Event({
                          'test1': 'event',
                          'priority': 0
                      })], False)
    memory_after_produce = psutil.Process().memory_info().vms
    rough_memory_for_non_consumable = \
        memory_after_produce - memory_before_produce

    self.assertLess(rough_memory_for_non_consumable,
                    rough_memory_for_events / PASS_CRITERIA_DIVIDER)

if __name__ == '__main__':
  logging.basicConfig(level=logging.INFO, format=log_utils.LOG_FORMAT)
  unittest.main()
