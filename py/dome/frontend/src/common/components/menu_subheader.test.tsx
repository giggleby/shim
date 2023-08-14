// Copyright 2023 The ChromiumOS Authors
// Use of this source code is governed by a BSD-style license that can be
// found in the LICENSE file.

import '@testing-library/jest-dom/extend-expect';
import {RenderResult} from '@testing-library/react';
import React from 'react';

import {wrappedRender} from '@app/__tests__/utils_wrapper';
import MenuSubheader from '@common/components/menu_subheader';

/**
 * MenuSubheader component test.
 */
describe('MenuSubheader', () => {
  const header = 'header name';
  const newHeader = 'new header name';
  let MenuSubheaderDOM: RenderResult;

  beforeEach(() => {
    MenuSubheaderDOM = wrappedRender(
      <MenuSubheader key="header">
        {header}
      </MenuSubheader>,
    );
  });

  test('verify that MenuSubheader dom node is correct', () => {
    const {getByRole} = MenuSubheaderDOM;
    const menuItemDom = getByRole('menuitem');
    expect(MenuSubheaderDOM).toBeDefined();
    expect(menuItemDom).toHaveTextContent(header);
    expect(menuItemDom).not.toHaveAttribute('tabindex');
  });

  test('check removeFocus has been called', () => {
    const {getByText, rerender} = MenuSubheaderDOM;
    rerender(
      <MenuSubheader key="header">
        {newHeader}
      </MenuSubheader>,
    );
    expect(getByText(newHeader)).not.toHaveAttribute('tabindex');
  });
});
