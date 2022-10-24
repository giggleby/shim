// Copyright 2018 The ChromiumOS Authors
// Use of this source code is governed by a BSD-style license that can be
// found in the LICENSE file.

import {createAction} from 'typesafe-actions';

import {Dispatch} from '@app/types';

const setError = createAction('SET_ERROR_MESSAGE', (resolve) =>
  (message: string, moreMessage: string) => resolve({message, moreMessage}));

const showErrorDialog = createAction('SHOW_ERROR_DIALOG');

const hideMoreErrorMessage = createAction('HIDE_MORE_ERROR_MESSAGE');

export const showMoreErrorMessage = createAction('SHOW_MORE_ERROR_MESSAGE');

export const hideErrorDialog = createAction('HIDE_ERROR_DIALOG');

export const basicActions = {
  setError,
  showErrorDialog,
  hideErrorDialog,
  showMoreErrorMessage,
  hideMoreErrorMessage,
};

// convenient wrapper of setError() + showErrorDialog()
export const setAndShowErrorDialog = (message: string, moreMessage: string) =>
  (dispatch: Dispatch) => {
    dispatch(setError(message, moreMessage));
    dispatch(showErrorDialog());
    dispatch(hideMoreErrorMessage());
  };
