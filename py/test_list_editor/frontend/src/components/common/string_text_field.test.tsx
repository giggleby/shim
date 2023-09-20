// Copyright 2023 The ChromiumOS Authors
// Use of this source code is governed by a BSD-style license that can be
// found in the LICENSE file.

import "@testing-library/jest-dom";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { StringTextField, StringTextFieldProps } from "./string_text_field";

describe("String Field display test", () => {
  const onChangeMock = jest.fn();
  const setupProps: StringTextFieldProps = {
    value: "a",
    validateJSON: false,
    onChange: onChangeMock,
  };
  beforeEach(() => {
    onChangeMock.mockReset();
    setupProps.value = "a";
    setupProps.validateJSON = false;
  });
  test("Renders correctly", () => {
    render(<StringTextField {...setupProps} />);
    expect(screen.getByText(/a/i)).toBeInTheDocument();
  });

  test("Update Values", async () => {
    const user = userEvent.setup();
    render(<StringTextField {...setupProps} />);
    await user.type(screen.getByText(/a/i), "b");
    expect(onChangeMock).toHaveBeenLastCalledWith("ab");
  });

  test("Display valid JSON object", () => {
    setupProps.value = '{"some_field": true}';
    setupProps.validateJSON = true;
    render(<StringTextField {...setupProps} />);
    expect(screen.queryByText(/invalid object/i)).not.toBeInTheDocument();
  });

  test("Display invalid JSON object", () => {
    setupProps.value = '{"some_field": }';
    setupProps.validateJSON = true;
    render(<StringTextField {...setupProps} />);
    expect(screen.getByText(/invalid object/i)).toBeInTheDocument();
  });
});
