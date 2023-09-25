// Copyright 2023 The ChromiumOS Authors
// Use of this source code is governed by a BSD-style license that can be
// found in the LICENSE file.

import "@testing-library/jest-dom";
import { render, screen } from "@testing-library/react";
import { EditEmptyItemConfigPanel } from "./edit_empty_item_config_panel";

describe("Edit Empty Item Config Panel", () => {
  test("renders correctly", () => {
    render(<EditEmptyItemConfigPanel />);

    expect(
      screen.getByText(/Select a test item to see more/i),
    ).toBeInTheDocument();
  });
});
