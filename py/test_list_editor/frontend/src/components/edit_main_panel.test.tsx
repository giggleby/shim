// Copyright 2023 The ChromiumOS Authors
// Use of this source code is governed by a BSD-style license that can be
// found in the LICENSE file.

import "@testing-library/jest-dom";
import { render, screen } from "@testing-library/react";
import { createMemoryRouter, RouterProvider } from "react-router-dom";
import { EditMainPanel } from "./edit_main_panel";

describe("Edit Main panel", () => {
  test("renders correctly", () => {
    const router = createMemoryRouter(
      [
        {
          path: "/",
          element: <EditMainPanel />,
          children: [{ index: true, element: <>Child Element</> }],
        },
      ],
      {
        initialEntries: ["/"],
        initialIndex: 0,
      },
    );
    render(<RouterProvider router={router} />);

    expect(screen.getByText(/Child Element/i)).toBeInTheDocument();
  });
});
