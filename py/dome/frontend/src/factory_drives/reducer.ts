// Copyright 2018 The Chromium OS Authors. All rights reserved.
// Use of this source code is governed by a BSD-style license that can be
// found in the LICENSE file.

import produce from 'immer';
import {ActionType, getType} from 'typesafe-actions';

import {basicActions as actions} from './actions';
import {FactoryDrive, FactoryDriveDirectory} from './types';

export interface FactoryDriveState {
  files: FactoryDrive[];
  dirs: FactoryDriveDirectory[];
}

type FactoryDriveAction = ActionType<typeof actions>;

const INITIAL_STATE = {
  files: [],
  dirs: [],
};

export default produce((draft: FactoryDriveState, action: FactoryDriveAction) => {
  switch (action.type) {
    case getType(actions.receiveFactoryDrives): {
      const {factoryDrives} = action.payload;
      draft.files = factoryDrives;
      return;
    }

    case getType(actions.updateFactoryDrive): {
      const {factoryDrive} = action.payload;
      draft.files[factoryDrive.id] = factoryDrive;
      return;
    }

    case getType(actions.receiveFactoryDriveDirs): {
      const {factoryDriveDirs} = action.payload;
      draft.dirs = factoryDriveDirs;
      return;
    }

    case getType(actions.updateFactoryDriveDir): {
      const {factoryDriveDir} = action.payload;
      draft.dirs[factoryDriveDir.id] = factoryDriveDir;
      return;
    }

    default:
      return;
  }
}, INITIAL_STATE);
