// Copyright 2023 The ChromiumOS Authors
// Use of this source code is governed by a BSD-style license that can be
// found in the LICENSE file.

import { render, screen } from "@testing-library/react";
import { SessionIdFloater } from "./session_id_display";

jest.mock("../hooks/session_id", () => {
  return {
    useSessionId: () => "12345678",
  };
});

describe("Session Id Floater Test", () => {
  test("Renders With Expected Session Id", () => {
    render(<SessionIdFloater />);
    screen.getByText(/12345678/);
  });
});
