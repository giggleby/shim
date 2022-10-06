// Copyright 2018 The ChromiumOS Authors
// Use of this source code is governed by a BSD-style license that can be
// found in the LICENSE file.

import {RootState} from '@app/types';

import {displayedState} from '@common/optimistic_update';

import {NAME} from './constants';
import {AuthState} from './reducer';

export const localState = (state: RootState): AuthState =>
  displayedState(state)[NAME];

export const isLoggedIn =
  (state: RootState): boolean | null => localState(state).isLoggedIn;
