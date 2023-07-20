// Copyright 2023 The ChromiumOS Authors
// Use of this source code is governed by a BSD-style license that can be
// found in the LICENSE file.

import "@testing-library/jest-dom";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { createMemoryRouter, RouterProvider } from "react-router-dom";
import { SearchBar } from "./search_bar";

describe("Search Bar Test", () => {
  test("Renders correctly", () => {
    render(<SearchBar />);
    const title = screen.getByText(/test list editor/i);
    expect(title).toBeInTheDocument();

    const feedbackButton = screen.getByText(/submit feedback/i);
    expect(feedbackButton).toBeInTheDocument();
  });

  test("Logo links back to main page", async () => {
    const router = createMemoryRouter(
      [
        {
          path: "/",
          element: <SearchBar />,
        },
      ],
      {
        initialEntries: ["/"],
        initialIndex: 0,
      },
    );
    render(<RouterProvider router={router} />);
    const user = userEvent.setup();
    await user.click(screen.getByText(/test list editor/i));

    const title = screen.getByText(/test list editor/i);
    expect(title).toBeInTheDocument();
  });
});
