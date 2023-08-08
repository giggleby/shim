// Copyright 2023 The ChromiumOS Authors
// Use of this source code is governed by a BSD-style license that can be
// found in the LICENSE file.

import '@testing-library/jest-dom/extend-expect';
import {act, fireEvent} from '@testing-library/react';
import React from 'react';

import {wrappedRender} from '@app/__tests__/utils_wrapper';
import CodeCopyButton from '@common/components/code_copy_button';

Object.assign(navigator, {
  clipboard: {
    writeText: jest.fn().mockImplementation(() => Promise.resolve()),
  },
});

/**
 * CodeCopyButton component test.
 */
describe('CodeCopyButton', () => {
  let node: HTMLElement;
  const code = 'pwd && ls';

  beforeEach(() => {
    const {getByRole} =
      wrappedRender(<CodeCopyButton code={code} />);
    node = getByRole('button');
  });

  test('verify that CodeCopyButton dom node is correct', () => {
    expect(node).toBeDefined();
    expect(node).toHaveTextContent('Copy');
  });

  test('click the CodeCopyButton', () => {
    jest.useFakeTimers();
    expect(setTimeout).not.toHaveBeenCalled();

    fireEvent.click(node);
    expect(node).toHaveTextContent('Copied!');

    act(() => {
      jest.runAllTimers();
    });
    expect(setTimeout).toHaveBeenCalled();

    jest.useRealTimers();
  });

  test('should call clipboard.writeText', () => {
    expect(navigator.clipboard.writeText).toHaveBeenCalledWith(code);
  });
});
