#!/usr/bin/env python
# Copyright (c) 2010 The Chromium OS Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.
"""
This module provides basic encode and decode functionality to the flashrom
memory map (FMAP) structure.

Usage:
  (decode)
  obj = fmap_decode(blob)
  print obj

  (encode)
  blob = fmap_encode(obj)
  open('output.bin', 'w').write(blob)

  The object returned by fmap_decode is a dictionary with names defined in
  fmap.h. A special property 'FLAGS' is provided as a readable and read-only
  tuple of decoded area flags.
"""


import struct


# constants imported from lib/fmap.h
FMAP_SIGNATURE = "__FMAP__"
FMAP_VER_MAJOR = 1
FMAP_VER_MINOR_MIN = 0
FMAP_VER_MINOR_MAX = 1
FMAP_STRLEN = 32

FMAP_FLAGS = {
    'FMAP_AREA_STATIC': 1 << 0,
    'FMAP_AREA_COMPRESSED': 1 << 1,
}

FMAP_HEADER_NAMES = (
    'signature',
    'ver_major',
    'ver_minor',
    'base',
    'size',
    'name',
    'nareas',
)

FMAP_AREA_NAMES = (
    'offset',
    'size',
    'name',
    'flags',
)


# format string
FMAP_HEADER_FORMAT = "<8sBBQI%dsH" % (FMAP_STRLEN)
FMAP_AREA_FORMAT = "<II%dsH" % (FMAP_STRLEN)


def _fmap_decode_header(blob, offset):
  """ (internal) Decodes a FMAP header from blob by offset"""
  header = {}
  for (name, value) in zip(FMAP_HEADER_NAMES,
                           struct.unpack_from(FMAP_HEADER_FORMAT,
                                              blob,
                                              offset)):
    header[name] = value

  if header['signature'] != FMAP_SIGNATURE:
    raise struct.error('Invalid signature')
  if (header['ver_major'] != FMAP_VER_MAJOR or
      header['ver_minor'] < FMAP_VER_MINOR_MIN or
      header['ver_minor'] > FMAP_VER_MINOR_MAX):
    raise struct.error('Incompatible version')

  # convert null-terminated names
  header['name'] = header['name'].strip(chr(0))
  return (header, struct.calcsize(FMAP_HEADER_FORMAT))


def _fmap_decode_area(blob, offset):
  """ (internal) Decodes a FMAP area record from blob by offset """
  area = {}
  for (name, value) in zip(FMAP_AREA_NAMES,
                           struct.unpack_from(FMAP_AREA_FORMAT, blob, offset)):
    area[name] = value
  # convert null-terminated names
  area['name'] = area['name'].strip(chr(0))
  # add a (readonly) readable FLAGS
  area['FLAGS'] = _fmap_decode_area_flags(area['flags'])
  return (area, struct.calcsize(FMAP_AREA_FORMAT))


def _fmap_decode_area_flags(area_flags):
  """ (internal) Decodes a FMAP flags property """
  return tuple([name for name in FMAP_FLAGS if area_flags & FMAP_FLAGS[name]])


def fmap_decode(blob, offset=None):
  """ Decodes a blob to FMAP dictionary object.

  Arguments:
    blob: a binary data containing FMAP structure.
    offset: starting offset of FMAP. When omitted, fmap_decode will search in
            the blob.
  """
  fmap = {}
  if offset == None:
    # try search magic in fmap
    offset = blob.find(FMAP_SIGNATURE)
  (fmap, size) = _fmap_decode_header(blob, offset)
  fmap['areas'] = []
  offset = offset + size
  for _ in range(fmap['nareas']):
    (area, size) = _fmap_decode_area(blob, offset)
    offset = offset + size
    fmap['areas'].append(area)
  return fmap


def _fmap_encode_header(obj):
  """ (internal) Encodes a FMAP header """
  values = [obj[name] for name in FMAP_HEADER_NAMES]
  return struct.pack(FMAP_HEADER_FORMAT, *values)


def _fmap_encode_area(obj):
  """ (internal) Encodes a FMAP area entry """
  values = [obj[name] for name in FMAP_AREA_NAMES]
  return struct.pack(FMAP_AREA_FORMAT, *values)


def fmap_encode(obj):
  """ Encodes a FMAP dictionary object to blob.

  Arguments
    obj: a FMAP dictionary object.
  """
  # fix up values
  obj['nareas'] = len(obj['areas'])
  # TODO(hungte) re-assign signature / version?
  blob = _fmap_encode_header(obj)
  for area in obj['areas']:
    blob = blob + _fmap_encode_area(area)
  return blob


def main():
  """Unit test."""
  blob = open('bin/example.bin').read()
  obj = fmap_decode(blob)
  print obj
  blob2 = fmap_encode(obj)
  obj2 = fmap_decode(blob2)
  print obj2
  assert obj == obj2


if __name__ == '__main__':
  main()
