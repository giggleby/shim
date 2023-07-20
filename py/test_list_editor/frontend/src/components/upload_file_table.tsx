// Copyright 2023 The ChromiumOS Authors
// Use of this source code is governed by a BSD-style license that can be
// found in the LICENSE file.

import Button from "@mui/material/Button";
import Container from "@mui/material/Container";
import Divider from "@mui/material/Divider";
import Grid from "@mui/material/Grid";
import List from "@mui/material/List";
import ListItem from "@mui/material/ListItem";
import Stack from "@mui/material/Stack";
import Typography from "@mui/material/Typography";
import React, { useState } from "react";
import { Link } from "react-router-dom";
import { UploadDialog } from "./upload_dialog";

// TODO: Pass files states into upload dialog to prevent duplicates
// TODO: Set main file (the file which will be loaded into DUT) in edit space.

export const UploadFileTable: React.FC = () => {
  const [openDialog, setOpenDialog] = useState(false);
  const handleClickOpen = () => setOpenDialog(true);
  const handleClose = () => setOpenDialog(false);

  const [files, setFiles] = useState<string[]>([]);

  return (
    <Container>
      <Grid
        container
        direction="row"
        spacing={2}
        justifyContent="center"
      >
        <Button
          variant="outlined"
          sx={{ marginTop: 2 }}
          onClick={handleClickOpen}
        >
          Upload
        </Button>
      </Grid>
      <Divider sx={{ marginTop: 3 }} />

      <UploadDialog
        open={openDialog}
        addFile={(filename: string) =>
          setFiles((prevVal) => [...prevVal, filename])
        }
        setCloseDialog={handleClose}
      />
      <List>
        {files.map((value) => (
          <ListItem key={value}>
            <Stack
              direction="row"
              justifyContent="space-between"
              alignItems="center"
              sx={{ width: 1 }}
            >
              <Typography>{value}</Typography>
              <Link to={`/edit/${value}.test_list`}>
                <Button variant="contained">Start</Button>
              </Link>
            </Stack>
          </ListItem>
        ))}
      </List>
    </Container>
  );
};
