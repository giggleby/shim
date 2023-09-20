// Copyright 2023 The ChromiumOS Authors
// Use of this source code is governed by a BSD-style license that can be
// found in the LICENSE file.

import "@testing-library/jest-dom";
import { render, screen } from "@testing-library/react";
import { DisplayLabel, DisplayLabelProps } from "./display_label";

describe("Display Label test", () => {
  test("Renders correctly", () => {
    const setupProps: DisplayLabelProps = {
      label: "Key 123",
    };
    render(<DisplayLabel {...setupProps} />);
    expect(screen.getByText(/key/i)).toBeInTheDocument();
  });
});
