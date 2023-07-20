// Copyright 2023 The ChromiumOS Authors
// Use of this source code is governed by a BSD-style license that can be
// found in the LICENSE file.

import "@testing-library/jest-dom";
import { render, screen } from "@testing-library/react";
import { createMemoryRouter, RouterProvider } from "react-router-dom";
import { LandingHeader } from "./landing_header";

describe("Landing Header", () => {
  test("renders the Landing Header correctly", () => {
    const router = createMemoryRouter(
      [
        {
          path: "/",
          element: <LandingHeader />,
        },
      ],
      {
        initialEntries: ["/"],
        initialIndex: 0,
      },
    );
    render(<RouterProvider router={router} />);

    const title = screen.getByText(/Start new test list/i);
    expect(title).toBeInTheDocument();
  });
});
