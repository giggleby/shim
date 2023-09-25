// Copyright 2023 The ChromiumOS Authors
// Use of this source code is governed by a BSD-style license that can be
// found in the LICENSE file.

import Grid2 from "@mui/material/Unstable_Grid2";
import { Outlet } from "react-router-dom";
import { EditTestSequencePanel } from "./edit_test_sequence_panel";

export function EditMainPanel() {
  return (
    <Grid2
      container
      spacing="16px"
    >
      <Grid2 xs={2.5}>
        <EditTestSequencePanel />
      </Grid2>
      <Grid2 xs={9.5}>
        <Outlet />
      </Grid2>
    </Grid2>
  );
}
