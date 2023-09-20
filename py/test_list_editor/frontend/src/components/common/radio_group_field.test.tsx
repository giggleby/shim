// Copyright 2023 The ChromiumOS Authors
// Use of this source code is governed by a BSD-style license that can be
// found in the LICENSE file.

import "@testing-library/jest-dom";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { RadioGroupField, RadioGroupFieldProps } from "./radio_group_field";

describe("Radio Field Display test", () => {
  const onChangeMock = jest.fn();
  const setupProps: RadioGroupFieldProps = {
    value: "A",
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
    render(<RadioGroupField {...setupProps} />);

    ["A", "B"].forEach((value) => {
      expect(screen.getByText(value)).toBeInTheDocument();
    });
  });

  test("Click radio button", async () => {
    const user = userEvent.setup();
    render(<RadioGroupField {...setupProps} />);

    const buttonB = screen.getByLabelText(/B/);
    await user.click(buttonB);

    expect(onChangeMock).toHaveBeenCalledWith("b");
  });
});
