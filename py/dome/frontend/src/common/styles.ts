// Copyright 2018 The ChromiumOS Authors
// Use of this source code is governed by a BSD-style license that can be
// found in the LICENSE file.

import grey from '@mui/material/colors/grey';
import {CSSProperties} from '@mui/styles/withStyles';

export const thinScrollBarX: CSSProperties = {
  overflowX: 'auto',
  '&::-webkit-scrollbar': {
    height: 6,
    backgroundColor: grey[300],
  },
  '&::-webkit-scrollbar-thumb': {
    backgroundColor: grey[500],
  },
};

export const thinScrollBarY: CSSProperties = {
  overflowY: 'auto',
  '&::-webkit-scrollbar': {
    width: 6,
    backgroundColor: grey[300],
  },
  '&::-webkit-scrollbar-thumb': {
    backgroundColor: grey[500],
  },
};
