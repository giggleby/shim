// Copyright 2023 The ChromiumOS Authors
// Use of this source code is governed by a BSD-style license that can be
// found in the LICENSE file.

import '@testing-library/jest-dom/extend-expect';
import React from 'react';

import {wrappedRender} from '@app/__tests__/utils_wrapper';
import CodeSnippet from '@common/components/code_snippet';

/**
 * CodeSnippet component test.
 */
describe('CodeSnippet', () => {
  test('verify that CodeSnippet dom node is correct', () => {
    const code = 'pwd && ls';
    const CodeSnippetDOM = wrappedRender(
      <CodeSnippet value={code} html={code} />,
    );
    const {getByText, getByRole} = CodeSnippetDOM;
    expect(CodeSnippetDOM).toBeDefined();
    expect(getByText(code)).toHaveTextContent(code);
    expect(getByRole('button')).toHaveTextContent('Copy');
  });
});
