# Copyright 2017 The Chromium OS Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""File-based buffer common.

A file-based buffer which writes its events to a single file on disk, and
separately maintains metadata.

There are three files maintained, plus one for each consumer created:

  data.json:

    Stores actual data.  Each line corresponds to one event.  As events are
    written to disk, each one is given a sequence number.  Format of each line:

        [SEQ_NUM, {EVENT_DATA}, CRC_SUM]

    Writing SEQ_NUM to data.json is not strictly necessary since we keep track
    of sequence numbers in metadata, but it is useful for debugging, and could
    also help when restoring a corrupt database.

  metadata.json:

    Stores current sequence numbers and cursor positions.  The "first seq" and
    "start pos" are taken to be absolute to the original untruncated data file,
    and refer to the beginning of data currently stored on disk.

    So if seq=1 was consumed by all Consumers, and Truncate removed it from
    disk, first_seq would be set to 2.

    Note that since the cursor positions are absolute, start_pos must be
    subtracted to get the actual position in the file on disk, e.g.:

        f.seek(current_pos - start_pos)

  consumers.json:

    Stores a list of all active Consumers.  If a Consumer is removed, it will be
    removed from this list, but its metadata file will continue to exist.  If it
    is ever re-created, the existing metadata will be used.  If this is
    undesired behaviour, the metadata file for that Consumer should be manually
    deleted.

  consumer_X.json:

    Stores the sequence number and cursor position of a particular Consumer.


Versioning:

  Another concept that is worth explaining separately is "versioning".  We want
  to support truncating, that is, when our file contains N records which have
  already been consumed by all Consumers, and M remaining records, remove the
  first N records from the main data file in order to save disk space.  After
  rewriting the data file, update metadata accordingly.

  But what happens if a failure occurs in between these two steps?  Our "old"
  metadata now is now paired with a "new" data file, which means we will likely
  be unable to read anything properly.

  To solve this problem, before re-writing the main data file, we save a
  metadata file to disk with both "old" and "new" metadata versions *before*
  performing a truncate on the main data file.  The key is a CRC hash of the
  first line of the main data file.  When the buffer first starts, it will check
  to see which key matches the first line, and it will use this metadata
  version.

  Thus, if a failure occurs *before* writing the main data file, the "old"
  metadata can be used.  If a failure occurs *after* writing the main data file,
  the "new" metadata can be used.
"""

import contextlib
import copy
import json
import logging
import os
import shutil
import zlib

from cros.factory.instalog import datatypes
from cros.factory.instalog import lock_utils
from cros.factory.instalog import log_utils
from cros.factory.instalog import plugin_base
from cros.factory.instalog.utils import file_utils
from cros.factory.instalog.utils import json_utils

# The number of bytes to buffer when retrieving events from a file.
_BUFFER_SIZE_BYTES = 4 * 1024  # 4kb
# The sub-directory for storing pre-emitted events json from each producer.
_NON_CONSUMABLE_FILE_DIR = 'non_consumable_dir'


class SimpleFileException(Exception):
  """General exception type for this plugin."""


class NoAttachmentForCopying(Exception):
  """No attachment for copying to the buffer."""


def GetChecksumLegacy(data):
  """Generates an 8-character CRC32 checksum of given string."""
  # TODO(chuntsen): Remove this legacy function.
  # The function crc32() returns a signed 32-bit integer in Python2, but it
  # returns an unsigned 32-bit integer in Python3. To generate the same value
  # across all Python versions, we convert unsigned integer to signed integer.
  checksum = zlib.crc32(data.encode('utf-8'))
  if checksum >= 2**31:
    checksum -= 2**32
  return '{:08x}'.format(abs(checksum))


def GetChecksum(data):
  """Generates an 8-character CRC32 checksum of given string."""
  # The function crc32() returns a signed 32-bit integer in Python2, but it
  # returns an unsigned 32-bit integer in Python3. To generate the same value
  # across all Python versions, we use "crc32() & 0xffffffff".
  return '{:08x}'.format(zlib.crc32(data.encode('utf-8')) & 0xffffffff)


def FormatRecord(seq, record):
  """Returns a record formatted as a line to be written to disk."""
  data = '%d, %s' % (seq, record)
  checksum = GetChecksum(data)
  return '[%s, "%s"]\n' % (data, checksum)


def ParseRecord(line, logger_name=None):
  """Parses and returns a line from disk as a record.

  Returns:
    A tuple of (seq_number, record), or None on failure.
  """
  logger = logging.getLogger(logger_name)
  line_inner = line.rstrip()[1:-1]  # Strip [] and newline
  data, _, checksum = line_inner.rpartition(', ')
  # TODO(chuntsen): Change this method after a long time.
  checksum = checksum.strip('"')
  seq, _, record = data.partition(', ')
  if not seq or not record:
    logger.warning('Parsing error for record %s', line.rstrip())
    return None, None
  if checksum != GetChecksum(data) and checksum != GetChecksumLegacy(data):
    logger.warning('Checksum error for record %s', line.rstrip())
    return None, None
  return int(seq), record


def TryLoadJSON(path, logger_name=None):
  """Attempts to load JSON from the given file.

  Returns:
    Parsed data from the file.  None if the file does not exist.

  Raises:
    Exception if there was some other problem reading the file, or if something
    went wrong parsing the data.
  """
  logger = logging.getLogger(logger_name)
  if not os.path.isfile(path):
    logger.debug('%s: does not exist', path)
    return None
  try:
    return json_utils.LoadFile(path)
  except Exception:
    logger.exception('%s: Error reading disk or loading JSON', path)
    raise


def CopyAttachmentsToTempDir(att_paths, tmp_dir, logger_name=None):
  """Copys attachments to the temporary directory."""
  logger = logging.getLogger(logger_name)
  try:
    for att_path in att_paths:
      # Check that the source file exists.
      if not os.path.isfile(att_path):
        raise ValueError('Attachment path `%s` specified in event does not '
                         'exist' % att_path)
      target_path = os.path.join(tmp_dir, att_path.replace('/', '_'))
      logger.debug('Copying attachment: %s --> %s',
                   att_path, target_path)
      with open(target_path, 'wb') as dst_f:
        with open(att_path, 'rb') as src_f:
          shutil.copyfileobj(src_f, dst_f)
        # Fsync the file and the containing directory to make sure it
        # is flushed to disk.
        dst_f.flush()
        os.fdatasync(dst_f)
    # Fsync the containing directory to make sure all attachments are flushed
    # to disk.
    dirfd = os.open(tmp_dir, os.O_DIRECTORY)
    os.fsync(dirfd)
    os.close(dirfd)
    return True
  except Exception:
    logger.exception('Exception encountered when copying attachments')
    return False


def MoveAndWrite(config_dct, event_iter_factory):
  """Moves the atts, serializes events and writes them to the data_path.

  Args:
    config_dct: dictionary for metadata.
    event_iter_factory: factory to get the iterable EventIter.
  """
  logger = logging.getLogger(config_dct['logger_name'])
  metadata_dct = RestoreMetadata(config_dct)
  cur_seq = metadata_dct['last_seq'] + 1
  cur_pos = metadata_dct['end_pos'] - metadata_dct['start_pos']
  # Truncate the size of the file in case of a previously unfinished
  # transaction.
  with open(config_dct['data_path'], 'a', encoding='utf8') as f:
    f.truncate(cur_pos)

  with open(config_dct['data_path'], 'a', encoding='utf8') as f, \
       event_iter_factory.GetEventIter() as event_iter:
    # On some machines, the file handle offset isn't set to EOF until
    # a write occurs.  Thus we must manually seek to the end to ensure
    # that f.tell() will return useful results.
    f.seek(0, 2)  # 2 means use EOF as the reference point.
    assert f.tell() == cur_pos
    copied_paths = []
    cur_pos_backup = cur_pos
    try:
      for event in event_iter:
        for att_id, att_path in event.attachments.items():
          target_name = '%s_%s' % (cur_seq, att_id)
          target_path = os.path.join(config_dct['attachments_dir'], target_name)
          event.attachments[att_id] = target_name
          logger.debug('Relocating attachment %s: %s --> %s', att_id, att_path,
                       target_path)
          # Note: This could potentially overwrite an existing file that got
          # written just before Instalog process stopped unexpectedly.
          os.rename(att_path, target_path)
          copied_paths.append(target_path)

        logger.debug('Writing event with cur_seq=%d, cur_pos=%d', cur_seq,
                     cur_pos)
        output = FormatRecord(cur_seq, event.Serialize())

        # Store the version for SaveMetadata to use.
        if cur_pos == 0:
          metadata_dct['version'] = GetChecksum(output)

        f.write(output)
        cur_seq += 1
        cur_pos += len(output)

      if config_dct['args'].enable_fsync:
        # Fsync the file and the containing directory to make sure it
        # is flushed to disk.
        f.flush()
        os.fdatasync(f)
        dirfd = os.open(
            os.path.dirname(config_dct['data_path']), os.O_DIRECTORY)
        os.fsync(dirfd)
        os.close(dirfd)
    except Exception as e:
      f.truncate(cur_pos_backup)
      # Do its best to try to remove copied attachment, if failed to delete the
      # attachment, only output an log as the exception is re-raised.
      for path in copied_paths:
        try:
          os.unlink(path)
        except Exception:
          logger.error('failed to clean up copied attachment: %s', path)
      raise e
  metadata_dct['last_seq'] = cur_seq - 1
  metadata_dct['end_pos'] = metadata_dct['start_pos'] + cur_pos
  SaveMetadata(config_dct, metadata_dct)


def SaveMetadata(config_dct, metadata_dct, old_metadata_dct=None):
  """Writes metadata of main database to disk."""
  if not metadata_dct['version']:
    raise SimpleFileException('No `version` available for SaveMetadata')
  data = {metadata_dct['version']: metadata_dct}
  if old_metadata_dct and old_metadata_dct['version']:
    if metadata_dct['version'] == old_metadata_dct['version']:
      raise SimpleFileException(
          'Same `version` from new metadata and old metadata')
    data[old_metadata_dct['version']] = old_metadata_dct
  with file_utils.AtomicWrite(config_dct['metadata_path'], fsync=True) as f:
    json.dump(data, f)


def RestoreMetadata(config_dct):
  """Restores version from the main data file on disk.

  If the metadata file does not exist, will silently return.
  """
  logger = logging.getLogger(config_dct['logger_name'])
  metadata_dct = {'first_seq': 1, 'last_seq': 0,
                  'start_pos': 0, 'end_pos': 0,
                  'version': '00000000'}
  data = TryLoadJSON(config_dct['metadata_path'], logger.name)
  if data is not None:
    try:
      with open(config_dct['data_path'], 'r', encoding='utf8') as f:
        metadata_dct['version'] = GetChecksum(f.readline())
    except Exception:
      logger.error('Data file unexpectedly missing; resetting metadata')
      return metadata_dct
    if metadata_dct['version'] not in data:
      logger.error('Could not find metadata version %s (available: %s); '
                   'recovering metadata from data file',
                   metadata_dct['version'], ', '.join(data.keys()))
      RecoverMetadata(config_dct, metadata_dct)
      return metadata_dct
    if len(data) > 1:
      logger.info('Metadata contains multiple versions %s; choosing %s',
                  ', '.join(data.keys()), metadata_dct['version'])
    metadata_dct.update(data[metadata_dct['version']])
    if (metadata_dct['end_pos'] >
        metadata_dct['start_pos'] + os.path.getsize(config_dct['data_path'])):
      logger.error('end_pos in restored metadata is larger than start_pos + '
                   'data file; recovering metadata from data file')
      RecoverMetadata(config_dct, metadata_dct)
  else:
    if os.path.isfile(config_dct['data_path']):
      logger.error('Could not find metadata file, but we have data file; '
                   'recovering metadata from data file')
      RecoverMetadata(config_dct, metadata_dct)
    else:
      logger.info('Creating metadata file and data file')
      SaveMetadata(config_dct, metadata_dct)
      file_utils.TouchFile(config_dct['data_path'])
  return metadata_dct


def RecoverMetadata(config_dct, metadata_dct):
  """Recovers metadata from the main data file on disk.

  Uses the first valid record for first_seq and start_pos, and the last
  valid record for last_seq and end_pos.
  """
  logger = logging.getLogger(config_dct['logger_name'])
  first_record = True
  cur_pos = 0
  with open(config_dct['data_path'], 'r', encoding='utf8') as f:
    for line in f:
      seq, _unused_record = ParseRecord(line, config_dct['logger_name'])
      if first_record and seq:
        metadata_dct['first_seq'] = seq
        metadata_dct['start_pos'] = cur_pos
        first_record = False
      cur_pos += len(line)
      if seq:
        metadata_dct['last_seq'] = seq
        metadata_dct['end_pos'] = cur_pos
  logger.info('Finished recovering metadata; sequence range found: %d to %d',
              metadata_dct['first_seq'], metadata_dct['last_seq'])
  SaveMetadata(config_dct, metadata_dct)


def TruncateAttachments(config_dct, metadata_dct):
  """Deletes attachments of events no longer stored within data.json."""
  logger = logging.getLogger(config_dct['logger_name'])
  for fname in os.listdir(config_dct['attachments_dir']):
    fpath = os.path.join(config_dct['attachments_dir'], fname)
    if not os.path.isfile(fpath):
      continue
    seq, unused_underscore, unused_att_id = fname.partition('_')
    if not seq.isdigit():
      continue
    if int(seq) < metadata_dct['first_seq']:
      logger.debug('Truncating attachment (<seq=%d): %s',
                   metadata_dct['first_seq'], fname)
      os.unlink(fpath)


def Truncate(config_dct, min_seq, min_pos):
  """Truncates the main data file to only contain unprocessed records.

  See file-level docstring for more information about versions.
  """
  logger = logging.getLogger(config_dct['logger_name'])
  metadata_dct = RestoreMetadata(config_dct)
  # Does the buffer already have data in it?
  if not metadata_dct['version']:
    return
  if metadata_dct['first_seq'] == min_seq:
    logger.info('No need to truncate')
    return
  try:
    logger.debug('Will truncate up until seq=%d, pos=%d', min_seq, min_pos)

    # Prepare the old vs. new metadata to write to disk.
    old_metadata_dct = copy.deepcopy(metadata_dct)
    metadata_dct['first_seq'] = min_seq
    metadata_dct['start_pos'] = min_pos

    with file_utils.AtomicWrite(config_dct['data_path'], fsync=True) as new_f:
      # AtomicWrite opens a file handle to a temporary file right next to
      # the real file (data_path), so we can open a "read" handle on data_path
      # without affecting AtomicWrite's handle.  Only when AtomicWrite's context
      # block ends will the temporary be moved to replace data_path.
      with open(config_dct['data_path'], 'r', encoding='utf8') as old_f:
        old_f.seek(min_pos - old_metadata_dct['start_pos'])

        # Deal with the first line separately to get the new version.
        first_line = old_f.readline()
        metadata_dct['version'] = GetChecksum(first_line)
        new_f.write(first_line)

        shutil.copyfileobj(old_f, new_f)

      # Before performing the "replace" step of write-replace (when
      # the file_utils.AtomicWrite context ends), save metadata to disk in
      # case of disk failure.
      SaveMetadata(config_dct, metadata_dct, old_metadata_dct)

    # After we use AtomicWrite, we can remove old metadata.
    SaveMetadata(config_dct, metadata_dct)

  except Exception:
    logger.exception('Exception occurred during Truncate operation')
    raise


class BufferFile(log_utils.LoggerMixin):

  def __init__(self, args, logger_name, data_dir):
    """Sets up the plugin."""
    self.args = args
    self.logger = logging.getLogger(logger_name)
    self.data_dir = data_dir

    self.data_path = os.path.join(
        data_dir, 'data.json')
    self.metadata_path = os.path.join(
        data_dir, 'metadata.json')
    self.consumers_list_path = os.path.join(
        data_dir, 'consumers.json')
    self.consumer_path_format = os.path.join(
        data_dir, 'consumer_%s.json')
    self.attachments_dir = os.path.join(
        data_dir, 'attachments')
    if not os.path.exists(self.attachments_dir):
      os.makedirs(self.attachments_dir)

    # Lock for writing to the self.data_path file.  Used by
    # Produce and Truncate.
    self.data_write_lock = lock_utils.Lock(logger_name)

    # Lock for modifying the self.consumers variable or for
    # preventing other threads from changing it.
    self._consumer_lock = lock_utils.Lock(logger_name)
    self.consumers = {}

    self._RestoreConsumers()

  @property
  def first_seq(self):
    return RestoreMetadata(self.ConfigToDict())['first_seq']

  @property
  def last_seq(self):
    return RestoreMetadata(self.ConfigToDict())['last_seq']

  @property
  def start_pos(self):
    return RestoreMetadata(self.ConfigToDict())['start_pos']

  @property
  def end_pos(self):
    return RestoreMetadata(self.ConfigToDict())['end_pos']

  @property
  def version(self):
    return RestoreMetadata(self.ConfigToDict())['version']

  def _SaveConsumers(self):
    """Saves the current list of active Consumers to disk."""
    with file_utils.AtomicWrite(self.consumers_list_path, fsync=True) as f:
      json.dump(list(self.consumers), f)

  def _RestoreConsumers(self):
    """Restore Consumers from disk.

    Creates a corresponding Consumer object for each Consumer listed on disk.
    Only ever called when the buffer first starts up, so we don't need to
    check for any existing Consumers in self.consumers.
    """
    data = TryLoadJSON(self.consumers_list_path, self.logger.name)
    if data:
      for name in data:
        self.consumers[name] = self._CreateConsumer(name)

  def ExternalizeEvent(self, event):
    """Modifies attachment paths of given event to be absolute."""
    for att_id in event.attachments.keys():
      # Reconstruct the full path to the attachment on disk.
      event.attachments[att_id] = os.path.abspath(os.path.join(
          self.attachments_dir, event.attachments[att_id]))
    return event

  def ConfigToDict(self):
    return {'logger_name': self.logger.name, 'args': self.args,
            'data_dir': self.data_dir, 'data_path': self.data_path,
            'metadata_path': self.metadata_path,
            'consumers_list_path': self.consumers_list_path,
            'consumer_path_format': self.consumer_path_format,
            'attachments_dir': self.attachments_dir}

  def ProduceEvents(self, event_iter_factory, process_pool=None):
    """Moves attachments, serializes events and writes them to the data_path."""
    with self.data_write_lock:
      # If we are going to write the first line which will change the version,
      # we should prevent the data and metadata from being read by consumers.
      metadata_dct = RestoreMetadata(self.ConfigToDict())
      first_line = (metadata_dct['start_pos'] == metadata_dct['end_pos'])
      try:
        if first_line:
          self._consumer_lock.acquire()
          for consumer in self.consumers.values():
            consumer.read_lock.acquire()

        if process_pool is None:
          MoveAndWrite(self.ConfigToDict(), event_iter_factory)
        else:
          # Passes a factory object to create event iterator due to some members
          # and objects can not be pickled and thus can not be send to different
          # processes.
          process_pool.apply(MoveAndWrite,
                             (self.ConfigToDict(), event_iter_factory))

      except Exception as e:
        self.exception('Exception occurred during ProduceEvents operation')
        raise e
      finally:
        # Ensure that regardless of any errors, locks are released.
        if first_line:
          for consumer in self.consumers.values():
            consumer.read_lock.CheckAndRelease()
          self._consumer_lock.CheckAndRelease()

  def _GetFirstUnconsumedRecord(self):
    """Returns the seq and pos of the first unprocessed record.

    Checks each Consumer to find the earliest unprocessed record, and returns
    that record's seq and pos.
    """
    metadata_dct = RestoreMetadata(self.ConfigToDict())
    min_seq = metadata_dct['last_seq'] + 1
    min_pos = metadata_dct['end_pos']
    for consumer in self.consumers.values():
      min_seq = min(min_seq, consumer.cur_seq)
      min_pos = min(min_pos, consumer.cur_pos)
    return min_seq, min_pos

  def Truncate(self, truncate_attachments=True, process_pool=None):
    """Truncates the main data file to only contain unprocessed records.

    See file-level docstring for more information about versions.

    Args:
      truncate_attachments: Whether or not to truncate attachments.
                             For testing.
    """
    new_metadata_dct = {}
    with self.data_write_lock, self._consumer_lock:
      min_seq, min_pos = self._GetFirstUnconsumedRecord()
      try:
        for consumer in self.consumers.values():
          consumer.read_lock.acquire()
        if process_pool is None:
          Truncate(self.ConfigToDict(), min_seq, min_pos)
        else:
          process_pool.apply(
              Truncate,
              (self.ConfigToDict(), min_seq, min_pos))
        new_metadata_dct = RestoreMetadata(self.ConfigToDict())
      except Exception:
        self.exception('Exception occurred during Truncate operation')
        # If any exceptions occurred, restore metadata, to make sure we are
        # using the correct version, since we aren't sure if the write succeeded
        # or not.
        raise
      finally:
        # Ensure that regardless of any errors, locks are released.
        for consumer in self.consumers.values():
          consumer.read_lock.CheckAndRelease()
    # Now that we have written the new data and metadata to disk, remove any
    # unused attachments.
    if truncate_attachments:
      TruncateAttachments(self.ConfigToDict(), new_metadata_dct)

  def _CreateConsumer(self, name):
    """Returns a new Consumer object with the given name."""
    return Consumer(
        name, self, self.consumer_path_format % name, self.logger.name)

  def AddConsumer(self, name):
    """See BufferPlugin.AddConsumer."""
    self.debug('Add consumer %s', name)
    with self.data_write_lock, self._consumer_lock:
      if name in self.consumers:
        raise SimpleFileException('Consumer %s already exists' % name)
      self.consumers[name] = self._CreateConsumer(name)
      self._SaveConsumers()

  def RemoveConsumer(self, name):
    """See BufferPlugin.RemoveConsumer."""
    self.debug('Remove consumer %s', name)
    with self.data_write_lock, self._consumer_lock:
      if name not in self.consumers:
        raise SimpleFileException('Consumer %s does not exist' % name)
      del self.consumers[name]
      self._SaveConsumers()

  def ListConsumers(self):
    """See BufferPlugin.ListConsumers."""
    with self._consumer_lock:
      # cur_seq represents the sequence ID of the consumer's next event.  If
      # that event doesn't exist yet, it will be set to the next (non-existent)
      # sequence ID.  We must subtract 1 to get the "last completed" event.
      cur_seqs = {key: consumer.cur_seq - 1
                  for key, consumer in self.consumers.items()}
      # Grab last_seq at the end, in order to guarantee that for any consumer,
      # last_seq >= cur_seq, and that all last_seq are equal.
      last_seq = self.last_seq
      return {key: (cur_seq, last_seq)
              for key, cur_seq in cur_seqs.items()}

  def Consume(self, name):
    """See BufferPlugin.Consume."""
    return self.consumers[name].CreateStream()


class Consumer(log_utils.LoggerMixin, plugin_base.BufferEventStream):
  """Represents a Consumer and its BufferEventStream.

  Since SimpleFile has only a single database file, there can only ever be one
  functioning BufferEventStream at any given time.  So we bundle the Consumer
  and its BufferEventStream into one object.  When CreateStream is called, a
  lock is acquired and the Consumer object is return.  The lock must first be
  acquired before any of Next, Commit, or Abort can be used.
  """

  def __init__(self, name, simple_file, metadata_path, logger_name):
    self.name = name
    self.simple_file = simple_file
    self.metadata_path = metadata_path
    self.logger = logging.getLogger(logger_name)

    self._stream_lock = lock_utils.Lock(logger_name)
    self.read_lock = lock_utils.Lock(logger_name)
    self.read_buf = []

    with self.read_lock:
      metadata_dct = RestoreMetadata(self.simple_file.ConfigToDict())
    self.cur_seq = metadata_dct['first_seq']
    self.cur_pos = metadata_dct['start_pos']
    self.new_seq = self.cur_seq
    self.new_pos = self.cur_pos

    # Try restoring metadata, if it exists.
    self.RestoreConsumerMetadata()
    self._SaveMetadata()

  def CreateStream(self):
    """Creates a BufferEventStream object to be used by Instalog core.

    Since this class doubles as BufferEventStream, we mark that the
    BufferEventStream is "unexpired" by setting self._stream_lock,
    and return self.

    Returns:
      `self` if BufferEventStream not already in use, None if busy.
    """
    return self if self._stream_lock.acquire(False) else None

  def _SaveMetadata(self):
    """Saves metadata for this Consumer to disk (seq and pos)."""
    data = {'cur_seq': self.cur_seq,
            'cur_pos': self.cur_pos}
    with file_utils.AtomicWrite(self.metadata_path, fsync=True) as f:
      json.dump(data, f)

  def RestoreConsumerMetadata(self):
    """Restores metadata for this Consumer from disk (seq and pos).

    On each restore, ensure that the available window of records on disk has
    not surpassed our own current record.  How would this happen?  If the
    Consumer is removed, records it still hasn't read are truncated from the
    main database, and the Consumer is re-added under the same name.

    If the metadata file does not exist, will silently return.
    """
    data = TryLoadJSON(self.metadata_path, self.logger.name)
    if data is not None:
      if 'cur_seq' not in data or 'cur_pos' not in data:
        self.error('Consumer %s metadata file invalid; resetting', self.name)
        return
      # Make sure we are still ahead of simple_file.
      with self.read_lock:
        metadata_dct = RestoreMetadata(self.simple_file.ConfigToDict())
      self.cur_seq = min(max(metadata_dct['first_seq'], data['cur_seq']),
                         metadata_dct['last_seq'] + 1)
      self.cur_pos = min(max(metadata_dct['start_pos'], data['cur_pos']),
                         metadata_dct['end_pos'])
      if (data['cur_seq'] < metadata_dct['first_seq'] or
          data['cur_seq'] > (metadata_dct['last_seq'] + 1)):
        self.error('Consumer %s cur_seq=%d is out of buffer range %d to %d, '
                   'correcting to %d', self.name, data['cur_seq'],
                   metadata_dct['first_seq'], metadata_dct['last_seq'] + 1,
                   self.cur_seq)
      self.new_seq = self.cur_seq
      self.new_pos = self.cur_pos

  def _Buffer(self):
    """Returns a list of pending records.

    Stores the current buffer internally at self.read_buf.  If it already has
    data in it, self.read_buf will be returned as-is.  It will be "refilled"
    when it is empty.

    Reads up to _BUFFER_SIZE_BYTES from the file on each "refill".

    Returns:
      A list of records, where each is a three-element tuple:
        (record_seq, record_data, line_bytes).
    """
    if self.read_buf:
      return self.read_buf
    # Does the buffer already have data in it?
    if not os.path.exists(self.simple_file.data_path):
      return self.read_buf
    self.debug('_Buffer: waiting for read_lock')
    try:
      # When the buffer is truncating, we can't get the read_lock.
      if not self.read_lock.acquire(timeout=0.5):
        return []
      metadata_dct = RestoreMetadata(self.simple_file.ConfigToDict())
      with open(self.simple_file.data_path, 'r', encoding='utf8') as f:
        cur = self.new_pos - metadata_dct['start_pos']
        f.seek(cur)
        total_bytes = 0
        skipped_bytes = 0
        for line in f:
          if total_bytes > _BUFFER_SIZE_BYTES:
            break
          size = len(line)
          cur += size
          if cur > (metadata_dct['end_pos'] - metadata_dct['start_pos']):
            break
          seq, record = ParseRecord(line, self.logger.name)
          if seq is None:
            # Parsing of this line failed for some reason.
            skipped_bytes += size
            continue
          # Only add to total_bytes for a valid line.
          total_bytes += size
          # Include any skipped bytes from previously skipped records in the
          # "size" of this record, in order to allow the consumer to skip to the
          # proper offset.
          self.read_buf.append((seq, record, size + skipped_bytes))
          skipped_bytes = 0
    finally:
      self.read_lock.CheckAndRelease()
    return self.read_buf

  def _Next(self):
    """Helper for Next, also used for testing purposes.

    Returns:
      A tuple of (seq, record), or (None, None) if no records available.
    """
    if not self._stream_lock.IsHolder():
      raise plugin_base.EventStreamExpired
    buf = self._Buffer()
    if not buf:
      return None, None
    seq, record, size = buf.pop(0)
    self.new_seq = seq + 1
    self.new_pos += size
    return seq, record

  def Next(self):
    """See BufferEventStream.Next."""
    seq, record = self._Next()
    if not seq:
      return None
    event = datatypes.Event.Deserialize(record)
    return self.simple_file.ExternalizeEvent(event)

  def Commit(self):
    """See BufferEventStream.Commit."""
    if not self._stream_lock.IsHolder():
      raise plugin_base.EventStreamExpired
    self.cur_seq = self.new_seq
    self.cur_pos = self.new_pos
    # Ensure that regardless of any errors, locks are released.
    try:
      self._SaveMetadata()
    except Exception:
      # TODO(kitching): Instalog core or PluginSandbox should catch this
      #                 exception and attempt to safely shut down.
      self.exception('Commit: Write exception occurred, Events may be '
                     'processed by output plugin multiple times')
    finally:
      try:
        self._stream_lock.release()
      except Exception:
        # TODO(kitching): Instalog core or PluginSandbox should catch this
        #                 exception and attempt to safely shut down.
        self.exception('Commit: Internal error occurred')

  def Abort(self):
    """See BufferEventStream.Abort."""
    if not self._stream_lock.IsHolder():
      raise plugin_base.EventStreamExpired
    self.new_seq = self.cur_seq
    self.new_pos = self.cur_pos
    self.read_buf = []
    try:
      self._stream_lock.release()
    except Exception:
      # TODO(kitching): Instalog core or PluginSandbox should catch this
      #                 exception and attempt to safely shut down.
      self.exception('Abort: Internal error occurred')


class NonConsumableEventsManager:
  """Manages pre-emitted events and files storing these events.

  The NonConsumableEventsManager is responsible for managing and providing
  NonConsumableFile, an object that stores and provides the pre-emitted events
  by each producer. Each producer has its own pre-emit json file,
  and all pre-emit json files are stored under the _NON_CONSUMABLE_FILE_DIR.
  The `SetUp` function call is required for setting up this manager with the
  path provided, which is for storing pre-emit json files. The directory is
  created, or cleaned up while calling the `SetUp` function. The access of
  NonConsumableFile of for each producer is thread-safe.
  """

  def __init__(self):
    self._dir_path = ''
    self._logger_name = None
    self._producers_lock = None
    self._producers = {}

  def SetUp(self, root_path, logger_name, dir_suffix=''):
    """Sets up the manager with creating or cleaning up the directory."""
    self._logger_name = logger_name
    # _producers maps the string key `plugin_id` to the NonConsumableFile object
    # for each producer, with the _producers_lock to prevent from getting race
    # condition while creating/accessing a key.
    self._producers_lock = lock_utils.Lock(self._logger_name)
    self._producers = {}
    dir_name = _NON_CONSUMABLE_FILE_DIR
    if dir_suffix != '':
      dir_name = dir_name + '_' + dir_suffix
    self._dir_path = os.path.join(root_path, dir_name)
    if os.path.exists(self._dir_path):
      shutil.rmtree(self._dir_path)
    file_utils.TryMakeDirs(self._dir_path)

  def GetNonConsumableFile(self, producer):
    """Gets a NonConsumableFile object by the producer thread-safely.

    If the producer does not exist, a new NonConsumableFile is created, updated
    to the _producers, then is returned.
    """
    with self._producers_lock:
      if producer not in self._producers:
        self._producers[producer] = NonConsumableFile(self._dir_path, producer,
                                                      self._logger_name)
      return self._producers[producer]


class NonConsumableFile:
  """Interacts with the file storing pre-emitted events from a producer.

  NonConsumableFile is in charge of storing/moving pre-emitted events to/from a
  {plugin_id}.pre_emit.json file for one producer. The access of events is
  thread-safe.
  """

  def __init__(self, dir_root_path, producer, logger_name):
    self._file_path = os.path.join(dir_root_path, f'{producer}.pre_emit.json')
    # Use Lock to safely lock every file-related critical methods with the
    # context manager.
    self._file_lock = lock_utils.Lock(logger_name)
    if not os.path.exists(self._file_path):
      file_utils.TouchFile(self._file_path)

  def StoreEvents(self, events):
    """Stores events to a pre-emit json file.

    The file is created if not exists.
    """
    with self._file_lock, open(self._file_path, 'a',
                               encoding='utf8') as event_file:
      for event in events:
        event_file.write(event.Serialize() + '\n')

  @contextlib.contextmanager
  def MoveFile(self):
    """Moves events and return the file path of the pre_emit file.

    The pre_emit file is replaced to an empty file after the function call.
    """
    with self._file_lock:
      yield self._file_path
      os.remove(self._file_path)
      file_utils.TouchFile(self._file_path)


class EventIterFactory:
  """Factory class to build a EventIter.

  The EventIterFactory defers the creation of the EventIter, which combines pre-
  emit events stored in the file and a list of events. This class provides a
  context manager fashion to open the file storing the pre-emit events and close
  it properly. The returned EventIter is equipped with a pre-process function,
  which copies attachments in a event, and update the attachment path in the
  event as well.

  Args:
    logger_name: Name used for logging.
    pre_emit_file_path: The file path to the pre-emit data file.
    events: list of events that to be iterated after events in pre-emitted
      events.
    attachments_tmp_dir_path: Directory path for storing attachments.
    keep_source_attachment: Boolean value for whether to keep the source
      attachment.
  """

  def __init__(self, logger_name, pre_emit_file_path, events,
               attachments_tmp_dir_path, keep_source_attachment):
    self._logger_name = logger_name
    self._file_path = pre_emit_file_path
    self._events = events
    self._attachments_tmp_dir_path = attachments_tmp_dir_path
    self._keep_source_attachment = keep_source_attachment
    self._attachment_sources = []

  @contextlib.contextmanager
  def GetEventIter(self):
    with open(self._file_path,
              encoding='utf8') as pre_emit_file, file_utils.TempDirectory(
                  dir=self._attachments_tmp_dir_path) as tmp_dir:
      yield EventIter(pre_emit_file, self._events,
                      self._GetPreProcessEventFn(tmp_dir))
      if not self._keep_source_attachment:
        logger = logging.getLogger(self._logger_name)
        for path in self._attachment_sources:
          try:
            os.unlink(path)
          except Exception:
            logger.exception(
                'Some of source attachment files (%s) could not '
                'be deleted; silently ignoring', path)

  def _GetPreProcessEventFn(self, copied_dir_path):

    def PreProcessEventFn(event):
      for att_id, att_path in event.attachments.items():
        event.attachments[att_id] = os.path.join(copied_dir_path,
                                                 att_path.replace('/', '_'))
        if not CopyAttachmentsToTempDir([att_path], copied_dir_path,
                                        self._logger_name):
          raise NoAttachmentForCopying
        if not self._keep_source_attachment:
          self._attachment_sources.append(att_path)
      return event

    return PreProcessEventFn


class EventIter:
  """Iterator to output next event combined from the file and list of events.

  Args:
    pre_emit_file: The file descriptor to read events.
    pre_process_fn: A function to manipulate event called before outputting a
      event to the iteration loop.
  """

  def __init__(self, pre_emit_file, events, pre_process_fn):
    self._file = pre_emit_file
    self._events = events
    self._cur_events_idx = 0
    self._pre_process_fn = pre_process_fn

  def __iter__(self):
    return self

  def __next__(self):
    event = self._NextEvent()
    if event is None:
      raise StopIteration
    return self._pre_process_fn(event)

  def _NextEvent(self):
    line = self._file.readline()
    # Reads non empty contents from file, deserialize and return it as an event.
    if line != '':
      return datatypes.Event.Deserialize(line)

    # Reads to the end of the file, iterating from the list
    # Reads all event in the self._events, reset status for the next iterating.
    if self._cur_events_idx >= len(self._events):
      return None
    ret = self._events[self._cur_events_idx]
    self._cur_events_idx += 1
    return ret
