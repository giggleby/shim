// Copyright 2023 The ChromiumOS Authors
// Use of this source code is governed by a BSD-style license that can be
// found in the LICENSE file.

import "@testing-library/jest-dom";
import { render, screen } from "@testing-library/react";
import { EditEmptyPanel } from "./edit_empty_panel";

describe("Edit Empty Panel", () => {
  test("renders correctly", () => {
    render(<EditEmptyPanel />);
    expect(
      screen.getByText(/Please go to a valid edit link/i),
    ).toBeInTheDocument();
  });
});
