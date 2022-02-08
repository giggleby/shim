// Copyright 2018 The Chromium OS Authors. All rights reserved.
// Use of this source code is governed by a BSD-style license that can be
// found in the LICENSE file.

import {RootState} from '@app/types';

import {displayedState} from '@common/optimistic_update';

import {NAME} from './constants';
import {PortState} from './reducer';
import {PortResponse} from './types';

export const localState = (state: RootState): PortState =>
  displayedState(state)[NAME];

export const getPorts =
  (state: RootState): PortResponse => localState(state).ports;
