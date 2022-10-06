// Copyright 2020 The ChromiumOS Authors
// Use of this source code is governed by a BSD-style license that can be
// found in the LICENSE file.

import {render} from '@testing-library/react';
import React from 'react';

import {HiddenFileSelect} from '../common/components/hidden_file_select';

/**
 * Simple import test file for Dome.
 */

it('Simple import test can pass', () => {
  expect(React).toEqual(expect.anything());
  expect(render).toEqual(expect.anything());
  expect(HiddenFileSelect).toEqual(expect.anything());
});
