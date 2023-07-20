// Copyright 2023 The ChromiumOS Authors
// Use of this source code is governed by a BSD-style license that can be
// found in the LICENSE file.

import Box from "@mui/material/Box";
import Container from "@mui/material/Container";
import Typography from "@mui/material/Typography";

// TODO: Include different ways to upload test list. E.g. files.

export function UploadHeader() {
  return (
    <div>
      <Container>
        <Box textAlign="center">
          {/* <Typography
            variant="h3"
            gutterBottom
          >
            Upload Test List
          </Typography> */}
          <Typography
            gutterBottom
            sx={{ mt: "100px" }}
          >
            Click the upload button to start the upload process.
          </Typography>
        </Box>
      </Container>
    </div>
  );
}
