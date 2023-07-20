// Copyright 2023 The ChromiumOS Authors
// Use of this source code is governed by a BSD-style license that can be
// found in the LICENSE file.

import "@testing-library/jest-dom";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { createMemoryRouter, RouterProvider } from "react-router-dom";
import { ILandingCardProps, LandingCard } from "./landing_card";

describe("Landing Card", () => {
  test("renders the landing card correctly", () => {
    const testData: ILandingCardProps = {
      title: "test",
      description: "123",
      ctaText: "click",
      ctaLink: "test123",
    };
    const router = createMemoryRouter(
      [
        {
          path: "/",
          element: <LandingCard {...testData} />,
        },
      ],
      {
        initialEntries: ["/"],
        initialIndex: 0,
      },
    );
    render(<RouterProvider router={router} />);

    const title = screen.getByText(/test/i);
    expect(title).toBeInTheDocument();

    const description = screen.getByText(/123/);
    expect(description).toBeInTheDocument();
  });
  test("goes to another link", async () => {
    const user = userEvent.setup();
    const testData: ILandingCardProps = {
      title: "test",
      description: "123",
      ctaText: "click",
      ctaLink: "test123",
    };
    const router = createMemoryRouter(
      [
        {
          path: "/",
          element: <LandingCard {...testData} />,
        },
        {
          path: "/test123",
          element: <>test passed</>,
        },
      ],
      {
        initialEntries: ["/"],
        initialIndex: 0,
      },
    );
    render(<RouterProvider router={router} />);

    const button = screen.getByText(/click/i);
    await user.click(button);

    const description = screen.getByText(/test passed/);
    expect(description).toBeInTheDocument();
  });
});
