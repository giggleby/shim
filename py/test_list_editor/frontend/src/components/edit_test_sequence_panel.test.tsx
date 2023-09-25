// Copyright 2023 The ChromiumOS Authors
// Use of this source code is governed by a BSD-style license that can be
// found in the LICENSE file.

import "@testing-library/jest-dom";
import { render, screen } from "@testing-library/react";
import { EditTestSequencePanel } from "./edit_test_sequence_panel";

describe("Edit Test Sequence Panel", () => {
  test("renders correctly", () => {
    render(<EditTestSequencePanel />);

    expect(
      screen.getByText(/Resolved Test Sequence Placeholder/i),
    ).toBeInTheDocument();
  });
});
