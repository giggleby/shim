// Copyright 2018 The ChromiumOS Authors
// Use of this source code is governed by a BSD-style license that can be
// found in the LICENSE file.

import {RootState} from '@app/types';

import {displayedState} from '@common/optimistic_update';

import {NAME} from './constants';
import {TaskState} from './reducer';
import {Task} from './types';

export const localState = (state: RootState): TaskState =>
  displayedState(state)[NAME];

export const getAllTasks =
  (state: RootState): Task[] => localState(state).tasks;
