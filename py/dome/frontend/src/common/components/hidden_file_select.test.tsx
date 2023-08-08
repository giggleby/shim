// Copyright 2020 The ChromiumOS Authors
// Use of this source code is governed by a BSD-style license that can be
// found in the LICENSE file.

import '@testing-library/jest-dom/extend-expect';
import {fireEvent, render} from '@testing-library/react';
import Enzyme, {shallow} from 'enzyme';
import Adapter from 'enzyme-adapter-react-16';
import React from 'react';

import {HiddenFileSelect} from '@common/components/hidden_file_select';

Enzyme.configure({adapter: new Adapter()});

/**
 * Simple import test file for Dome.
 */
test('Simple import test can pass', () => {
  expect(React).toEqual(expect.anything());
  expect(render).toEqual(expect.anything());
  expect(HiddenFileSelect).toEqual(expect.anything());
});

/**
 * HiddenFileSelect component test.
 */
describe('HiddenFileSelect', () => {
  let node: HTMLElement;
  let handleFileChange: (files: FileList | null) => undefined;

  beforeEach(() => {
    handleFileChange = jest.fn((files: FileList | null) => undefined);
    const {getByRole} =
      render(<HiddenFileSelect multiple onChange={handleFileChange} />);
    node = getByRole('textbox', {hidden: true});
  });

  test('verify that HiddenFileSelect dom node is correct', () => {
    expect(node).toBeDefined();
    expect(node).toHaveClass('hidden');
    expect(node).toHaveAttribute('type', 'file');
    expect(node).toHaveAttribute('multiple');
  });

  test('select file and trigger on file change', () => {
    const rows = ['chromeos', 'chrome os factory', 'chrome os factory dome'];
    const file = new File([rows.join('\n')], 'cros.csv');
    fireEvent.change(node, {target: {files: [file]}});
    expect(handleFileChange).toHaveBeenCalledWith([file]);
  });

  test('select an empty file and trigger the onchage event', () => {
    fireEvent.change(node, {target: {files: null}});
    expect(handleFileChange).not.toHaveBeenCalled();
  });

  test('the fileInputRef not be defined', async () => {
    const wrapper = shallow(
      <HiddenFileSelect multiple onChange={handleFileChange} />,
    );
    expect(wrapper.find('input')).toBeDefined();
  });
});
