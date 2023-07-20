// Copyright 2023 The ChromiumOS Authors
// Use of this source code is governed by a BSD-style license that can be
// found in the LICENSE file.

import "@testing-library/jest-dom";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { createMemoryHistory } from "history";
import React, { useState } from "react";
import { Router } from "react-router-dom";
import { UploadFileTable } from "./upload_file_table";

jest.mock("./upload_dialog", () => {
  return {
    UploadDialog: () => <div>UploadDialog</div>,
  };
});

// eslint-disable-next-line @typescript-eslint/no-unsafe-return
jest.mock("react", () => ({
  ...jest.requireActual("react"),
  useState: jest.fn(),
}));

describe("UploadFileTable", () => {
  test("renders the upload button", () => {
    jest
      .mocked(useState)
      .mockImplementation(jest.requireActual<typeof React>("react").useState);
    render(<UploadFileTable />);

    const uploadButton = screen.getByRole("button", { name: "Upload" });
    expect(uploadButton).toBeInTheDocument();
  });

  test("opens the dialog on upload button click", async () => {
    jest
      .mocked(useState)
      .mockImplementation(jest.requireActual<typeof React>("react").useState);
    render(<UploadFileTable />);

    const uploadButton = screen.getByRole("button", { name: "Upload" });
    await userEvent.click(uploadButton);

    const dialog = screen.getByText("UploadDialog");
    expect(dialog).toBeInTheDocument();
  });

  test("renders the test list correctly", () => {
    jest.mocked(useState).mockImplementation(() => [["main_xxx"], jest.fn()]);

    const history = createMemoryHistory();
    render(
      <Router
        location={history.location}
        navigator={history}
      >
        <UploadFileTable />
      </Router>,
    );
  });
});
