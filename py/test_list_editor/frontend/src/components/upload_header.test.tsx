// Copyright 2023 The ChromiumOS Authors
// Use of this source code is governed by a BSD-style license that can be
// found in the LICENSE file.

import "@testing-library/jest-dom";
import { render, screen } from "@testing-library/react";
import { UploadHeader } from "./upload_header";

describe("UploadHeaderComponent", () => {
  test("renders the component correctly", () => {
    render(<UploadHeader />);

    const uploadText = screen.getByText(/Click the upload button/i);
    expect(uploadText).toBeInTheDocument();
  });
});
