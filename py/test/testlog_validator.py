# -*- coding: utf-8 -*-
# Copyright 2016 The Chromium OS Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Various validation functions for FIELDS in testlog's Event-like object."""

import datetime
import logging
import os
import pprint
import re
import shutil

import factory_common  # pylint: disable=W0611
from cros.factory.test import testlog_utils
from cros.factory.utils import time_utils


class Validator(object):
  """Wrapper for functions that assign and validate values to Event object."""
  @staticmethod
  def Object(inst, key, value):
    # pylint: disable=W0212
    inst._data[key] = value

  @staticmethod
  def Long(inst, key, value):
    if not isinstance(value, (int, long)):
      raise ValueError(
          'key[%s] accepts type of int or long. Not %r '
          'Please convert before assign' % (key, type(value)))
    Validator.Object(inst, key, value)

  @staticmethod
  def Float(inst, key, value):
    if not isinstance(value, float):
      raise ValueError(
          'key[%s] accepts type of float. Not %r '
          'Please convert before assign' % (key, type(value)))
    Validator.Object(inst, key, value)

  @staticmethod
  def String(inst, key, value):
    if not isinstance(value, basestring):
      raise ValueError(
          'key[%s] accepts type of basestring. Not %r '
          'Please convert before assign' % (key, type(value)))
    Validator.Object(inst, key, value)

  @staticmethod
  def Boolean(inst, key, value):
    if not isinstance(value, bool):
      raise ValueError(
          'key[%s] accepts type of bool. Not %r '
          'Please convert before assign' % (key, type(value)))
    Validator.Object(inst, key, value)

  @staticmethod
  def Dict(inst, key, value):
    """Inserts an item into the inst._data[key].

    Assuming inst._data[key] is a dictionary, the inserted element will be
    inst_data[key][value['key']] = value['value'].
    """
    logging.debug('Validator.Dict called with (%s, %s)', key, value)
    if not 'key' in value or not 'value' in value or len(value.items()) != 2:
      raise ValueError(
          'Validator.Dict accepts value in form of {%r:..., %r:...}, not %s' % (
              'key', 'value', pprint.pformat(value)))

    # pylint: disable=W0212
    updated_dict = inst._data[key] if key in inst._data else dict()
    sub_key = value['key']
    if sub_key in updated_dict:
      raise ValueError(
          '%r is duplicated for field %s' % (sub_key, key))
    updated_dict[sub_key] = value['value']
    # TODO(itspeter): Check if anything left in value.
    # pylint: disable=W0212
    inst._data[key] = updated_dict

  @staticmethod
  def List(inst, key, value):
    logging.debug('Validator.List called with (%s, %s)', key, value)
    # pylint: disable=W0212
    updated_list = inst._data[key] if key in inst._data else list()
    updated_list.append(value)
    # pylint: disable=W0212
    inst._data[key] = updated_list

  @staticmethod
  def Time(inst, key, value):
    """Converts value into datetime object.

    The datetime object is expected to converts to ISO8601 format at the
    time that it convert to JSON string.
    """
    logging.debug('Validator.Time is called with (%s, %s)', key, value)
    if isinstance(value, basestring):
      d = testlog_utils.FromJSONDateTime(value)
    elif isinstance(value, datetime.datetime):
      d = value
    else:
      raise ValueError('Invalid `time` (%r) for Validator.Time' % value)
    # Round precision of microseconds to ensure equivalence after converting
    # to JSON and back again.
    d = d.replace(microsecond=(d.microsecond / 1000 * 1000))
    Validator.Object(inst, key, d)

  @staticmethod
  def Attachment(inst, key, value, testlog_getter_fn):
    logging.debug('Validator.Attachment is called: %s, %s', key, value)
    # TODO(itspeter): Move constants to a better place.
    PATH = 'path'
    MIME_TYPE = 'mimeType'
    DESCRIPTION = 'description'

    # Verify required fields
    sub_key = value['key']
    # TODO(itspeter): Figure out a long-term approach to avoid attchments
    #                 are processed twice (one on API call, one on
    #                 testlog.Collect.
    delete_after_move = value.get('delete', True)
    value = value['value']

    source_path = value.pop(PATH, None)
    if not source_path:
      raise ValueError('path field cannot be found')
    # Check if source_path exists
    # TODO(itspeter): Consider doing a lsof sanity check.
    if not os.path.exists(source_path):
      raise ValueError('not able to find file %s' % source_path)
    mime_type = value.pop(MIME_TYPE, None)
    if not isinstance(mime_type, basestring) or (
        not re.match(r'^[-\+\w]+/[-\+\w]+$', mime_type)):
      raise ValueError('mimeType(%r) is incorrect for file %s' % (
          mime_type, source_path))

    # Check if duplicated keys exist
    # pylint: disable=W0212
    updated_dict = inst._data[key] if key in inst._data else dict()
    if sub_key in updated_dict:
      raise ValueError(
          '%s is duplicated for field %s' % (sub_key, key))
    value_to_insert = {MIME_TYPE: mime_type}
    # Move the attachment file.
    folder = testlog_getter_fn().attachments_folder

    # First try with the same filename.
    # TODO(itspeter): kitching@ suggest we use {testRunId}_{attachmentName}
    target_path = os.path.join(folder, os.path.basename(source_path))
    if os.path.exists(target_path):
      target_path = None
      for _ in xrange(5):  # Try at most 5 times of adding a random UUID.
        uuid_target_path = os.path.join(folder, '%s_%s' % (
            time_utils.TimedUUID()[-12:], os.path.basename(source_path)))
        if not os.path.exists(uuid_target_path):
          target_path = uuid_target_path
          break
      if target_path is None:
        raise ValueError(
            'Try to get a lottery for yourself, with about a probability '
            'of %s, %s failed to find its way home' % (
                (1.0/16)**12, source_path))
    if delete_after_move:
      os.rename(source_path, target_path)
    else:
      shutil.copy(source_path, target_path)

    value_to_insert[PATH] = os.path.realpath(target_path)
    if DESCRIPTION in value:
      value_to_insert[DESCRIPTION] = value[DESCRIPTION]

    updated_dict[sub_key] = value_to_insert
    # TODO(itspeter): Check if anything left in value.
    # pylint: disable=W0212
    inst._data[key] = updated_dict

  @staticmethod
  def Status(inst, key, value):
    if value not in inst.STATUS:
      raise ValueError('Invalid status : %r' % value)
    Validator.Object(inst, key, value)
