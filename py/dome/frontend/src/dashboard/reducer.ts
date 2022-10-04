// Copyright 2018 The ChromiumOS Authors
// Use of this source code is governed by a BSD-style license that can be
// found in the LICENSE file.

import produce from 'immer';
import {combineReducers} from 'redux';
import {ActionType, getType} from 'typesafe-actions';

import {basicActions as actions} from './actions';
import {PortResponse} from './types';

export interface PortState {
  ports: PortResponse;
}

type PortAction = ActionType<typeof actions>;

const portsReducer = produce((draft: PortState, action: PortAction) => {
  switch (action.type) {
    case getType(actions.receivePorts):
      return action.payload.ports;

    case getType(actions.removePorts):
      const ports = Object.assign({}, action.payload.ports);
      ports.allPorts = action.payload.ports.allPorts.filter((port) => {
        return port.name !== action.payload.projectName;
      });
      return ports;

    default:
      return;
  }
}, {});

export default combineReducers<PortState, PortAction>({
  ports: portsReducer,
});
