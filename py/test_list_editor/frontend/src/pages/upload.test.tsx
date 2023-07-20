// Copyright 2023 The ChromiumOS Authors
// Use of this source code is governed by a BSD-style license that can be
// found in the LICENSE file.

import "@testing-library/jest-dom";
import { render } from "@testing-library/react";
import { createMemoryRouter, RouterProvider } from "react-router-dom";
import { Upload } from "./upload";

describe("Upload Page Test", () => {
  test("Renders correctly", () => {
    const router = createMemoryRouter([
      {
        path: "/",
        element: <Upload />,
      },
    ]);
    render(<RouterProvider router={router} />);
  });
});
