// Copyright 2018 The ChromiumOS Authors
// Use of this source code is governed by a BSD-style license that can be
// found in the LICENSE file.

import {RootState} from '@app/types';

import {displayedState} from '@common/optimistic_update';

import {NAME} from './constants';
import {FactoryDriveState} from './reducer';
import {FactoryDrive, FactoryDriveDirectory} from './types';

export const localState = (state: RootState): FactoryDriveState =>
  displayedState(state)[NAME];

export const getFactoryDrives =
  (state: RootState): FactoryDrive[] => localState(state).files;

export const getFactoryDriveDirs =
  (state: RootState): FactoryDriveDirectory[] => localState(state).dirs;
