// Copyright 2023 The ChromiumOS Authors
// Use of this source code is governed by a BSD-style license that can be
// found in the LICENSE file.

import "@testing-library/jest-dom";
import { render, screen } from "@testing-library/react";
import { EditItemConfigPanel } from "./edit_item_config_panel";

describe("Edit Item Config Panel", () => {
  test("renders correctly", () => {
    render(<EditItemConfigPanel />);
    expect(
      screen.getByText(/Test Item Config Panel Placeholder/i),
    ).toBeInTheDocument();
  });
});
