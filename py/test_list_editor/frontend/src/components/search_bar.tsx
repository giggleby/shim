// Copyright 2023 The ChromiumOS Authors
// Use of this source code is governed by a BSD-style license that can be
// found in the LICENSE file.

import AppBar from "@mui/material/AppBar";
import Box from "@mui/material/Box";
import Button from "@mui/material/Button";
import Link from "@mui/material/Link";
import Toolbar from "@mui/material/Toolbar";
import Typography from "@mui/material/Typography";

export function SearchBar() {
  return (
    <Box sx={{ width: 1, mb: "64px" }}>
      <AppBar
        position="fixed"
        sx={{ backgroundColor: "#00529b" }}
      >
        <Toolbar sx={{ display: "flex", justifyContent: "space-between" }}>
          <Link
            underline="none"
            href="/"
          >
            <Typography
              variant="h6"
              component="div"
              sx={{ flexGrow: 1, color: "white" }}
            >
              Test List Editor
            </Typography>
          </Link>
          <Button
            color="info"
            variant="contained"
            target="_blank"
            rel="noreferrer"
            href={"https://forms.gle/uzRgo1knbyviP3E48"}
          >
            Submit Feedback
          </Button>
        </Toolbar>
      </AppBar>
    </Box>
  );
}
