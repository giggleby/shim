// Copyright 2023 The ChromiumOS Authors
// Use of this source code is governed by a BSD-style license that can be
// found in the LICENSE file.

import {indigo} from '@mui/material/colors';
import {
  createTheme,
  ThemeProvider,
} from '@mui/material/styles';
import {render} from '@testing-library/react';
import React, {ReactElement} from 'react';
import {Provider} from 'react-redux';
import {applyMiddleware, createStore} from 'redux';
import thunk from 'redux-thunk';

import root_reducer from '@app/root_reducer';

const THEME = {
  palette: {
    primary: indigo,
  },
};

export const wrappedRender = (
  ui: ReactElement,
  options?: any,
) => {
  // Wrap dispatch in a mock so it can be spied on.
  const store = createStore(root_reducer, applyMiddleware(thunk));
  store.dispatch = jest.fn(store.dispatch);

  const AllProviders = ({children}: any): ReactElement => {
    return (
      <ThemeProvider theme={createTheme(THEME)}>
        <Provider store={store}>
          {children}
        </Provider>
      </ThemeProvider>
    );
  };

  const returns = render(ui, {
    wrapper: AllProviders as any,
    ...options,
  });

  return {store, ...returns};
};
