// Copyright 2023 The ChromiumOS Authors
// Use of this source code is governed by a BSD-style license that can be
// found in the LICENSE file.

import "@testing-library/jest-dom";
import { render, screen } from "@testing-library/react";
import {
  createMemoryRouter,
  isRouteErrorResponse,
  RouterProvider,
  useRouteError,
} from "react-router-dom";
import { ErrorPage } from "./error";

jest.mock("react-router-dom", () => {
  // eslint-disable-next-line @typescript-eslint/no-unsafe-return
  return {
    ...jest.requireActual("react-router-dom"),
    useRouteError: jest.fn(),
    isRouteErrorResponse: jest.fn(),
  };
});

describe("Landing Header", () => {
  test("renders error type", () => {
    jest.mocked(useRouteError).mockImplementation(() => {
      return Error("Custom Error");
    });
    const router = createMemoryRouter([
      {
        path: "/",
        element: <ErrorPage />,
      },
    ]);

    render(<RouterProvider router={router}></RouterProvider>);

    expect(screen.getByText("Custom Error")).toBeInTheDocument();
  });
  test("renders error string", () => {
    jest.mocked(useRouteError).mockImplementation(() => {
      return "Error String";
    });
    const router = createMemoryRouter([
      {
        path: "/",
        element: <ErrorPage />,
      },
    ]);

    render(<RouterProvider router={router}></RouterProvider>);
    expect(screen.getByText("Error String")).toBeInTheDocument();
  });
  test("renders route error", () => {
    jest.mocked(isRouteErrorResponse).mockImplementation((val) => true);
    jest.mocked(useRouteError).mockImplementation(() => {
      return {
        error: {
          message: "router-error",
        },
      };
    });
    const router = createMemoryRouter([
      {
        path: "/",
        element: <ErrorPage />,
      },
    ]);

    render(<RouterProvider router={router}></RouterProvider>);
    expect(screen.getByText("router-error")).toBeInTheDocument();
  });
  test("renders route error statusText", () => {
    jest.mocked(isRouteErrorResponse).mockImplementation((val) => true);

    jest.mocked(useRouteError).mockImplementation(() => {
      return {
        statusText: "router-error",
      };
    });
    const router = createMemoryRouter([
      {
        path: "/",
        element: <ErrorPage />,
      },
    ]);

    render(<RouterProvider router={router}></RouterProvider>);
    expect(screen.getByText("router-error")).toBeInTheDocument();
  });
  test("renders Unknown Error", () => {
    jest.mocked(isRouteErrorResponse).mockImplementation((val) => false);

    jest.mocked(useRouteError).mockImplementation(() => {
      return 123;
    });
    const router = createMemoryRouter([
      {
        path: "/",
        element: <ErrorPage />,
      },
    ]);

    render(<RouterProvider router={router}></RouterProvider>);
    expect(screen.getByText("123")).toBeInTheDocument();
  });
});
