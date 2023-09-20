// Copyright 2023 The ChromiumOS Authors
// Use of this source code is governed by a BSD-style license that can be
// found in the LICENSE file.

import "@testing-library/jest-dom";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { SelectField, SelectFieldProps } from "./select_field";

describe("Select field test", () => {
  const onChangeMock = jest.fn();
  const setupProps: SelectFieldProps = {
    value: "a",
    options: [
      {
        label: "A",
        value: "a",
      },
      {
        label: "B",
        value: "b",
      },
    ],
    onChange: onChangeMock,
  };
  beforeEach(() => {
    onChangeMock.mockReset();
  });

  test("Renders correctly", () => {
    render(<SelectField {...setupProps} />);
    expect(screen.getByText(/a/i)).toBeInTheDocument();
  });
  test("Select other option.", async () => {
    const user = userEvent.setup();
    render(<SelectField {...setupProps} />);

    const selectField = screen.getByRole("button", { name: /A/ });
    await user.click(selectField);
    const optionB = screen.getByRole("option", { name: /B/ });
    expect(optionB).toBeInTheDocument();

    await user.click(optionB);
    expect(onChangeMock).toHaveBeenCalledWith("b");
  });
});
