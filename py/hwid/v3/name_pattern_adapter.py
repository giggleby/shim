# Copyright 2020 The Chromium OS Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

import io
import re
from typing import Optional


class NamePattern:

  def __init__(self, comp_cls):
    self.comp_cls = comp_cls
    self.pattern = re.compile(r'{comp_cls}_(\d+)(?:_(\d+))?(?:#.*)?$'.format(
        comp_cls=re.escape(comp_cls)))

  def Matches(self, tag):
    ret = self.pattern.match(tag)
    if ret:
      return int(ret.group(1)), int(ret.group(2) or 0)
    return None

  def GenerateAVLName(self, cid: int, qid: int = 0,
                      seq_no: Optional[int] = None):
    name_buf = io.StringIO()
    name_buf.write(self.comp_cls)
    name_buf.write('_')
    name_buf.write(str(cid))
    if qid:
      name_buf.write('_')
      name_buf.write(str(qid))
    if seq_no is not None:
      name_buf.write('#')
      name_buf.write(str(seq_no))
    return name_buf.getvalue()


class NamePatternAdapter:

  def GetNamePattern(self, comp_cls):
    return NamePattern(comp_cls)
