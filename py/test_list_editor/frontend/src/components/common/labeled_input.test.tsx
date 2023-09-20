// Copyright 2023 The ChromiumOS Authors
// Use of this source code is governed by a BSD-style license that can be
// found in the LICENSE file.

import "@testing-library/jest-dom";
import { render, screen } from "@testing-library/react";
import { LabeledInput, LabeledInputProps } from "./labeled_input";

describe("Labeled input display test", () => {
  test("Renders correctly", () => {
    const setupProps: LabeledInputProps = {
      label: <>Key 123</>,
      inputField: <>abc</>,
      labelWidth: 3,
      inputWidth: 4,
    };
    render(<LabeledInput {...setupProps} />);
    expect(screen.getByText(/Key/i)).toBeInTheDocument();

    expect(screen.getByText(/abc/i)).toBeInTheDocument();
  });
});
