// Copyright 2018 The ChromiumOS Authors
// Use of this source code is governed by a BSD-style license that can be
// found in the LICENSE file.

import {combineReducers} from 'redux';
import {ActionType, getType} from 'typesafe-actions';

import {basicActions as actions} from './actions';

export interface MessageObject {
  errorMessage: string;
  moreErrorMessage: string;
}

export interface ErrorState {
  show: boolean;
  showMore: boolean;
  message: MessageObject;
}

type ErrorAction = ActionType<typeof actions>;

export default combineReducers<ErrorState, ErrorAction>({
  show: (state = false, action) => {
    switch (action.type) {
      case getType(actions.showErrorDialog):
        return true;

      case getType(actions.hideErrorDialog):
        return false;

      default:
        return state;
    }
  },
  showMore: (state = false, action) => {
    switch (action.type) {
      case getType(actions.showMoreErrorMessage):
        return true;

      case getType(actions.hideMoreErrorMessage):
        return false;

      default:
        return state;
    }
  },
  message: (state = {errorMessage: '', moreErrorMessage: ''}, action) => {
    switch (action.type) {
      case getType(actions.setError):
        return {
          errorMessage: action.payload.message,
          moreErrorMessage: action.payload.moreMessage,
        };

      default:
        return state;
    }
  },
});
