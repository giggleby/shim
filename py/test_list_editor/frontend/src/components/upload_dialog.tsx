// Copyright 2023 The ChromiumOS Authors
// Use of this source code is governed by a BSD-style license that can be
// found in the LICENSE file.

// TODO: Display JSON code in codeblock with JSON syntax highlighting in the pop-up
import Box from "@mui/material/Box";
import Button from "@mui/material/Button";
import Dialog from "@mui/material/Dialog";
import DialogActions from "@mui/material/DialogActions";
import DialogContent from "@mui/material/DialogContent";
import DialogContentText from "@mui/material/DialogContentText";
import DialogTitle from "@mui/material/DialogTitle";
import TextField from "@mui/material/TextField";
import Typography from "@mui/material/Typography";
import React, { useState } from "react";
import { useFileEndpoint } from "../hooks/file";
import { useJSONValidation } from "../hooks/json";
import { FileObject } from "../services/fileService";

interface UploadDialogProps {
  open: boolean;
  setCloseDialog: () => void;
  addFile: (filename: string) => void;
}

// TODO: Better integration with UploadFileTable
// (1) Show warnings when same name are used.

function getValidationTextStyle(text: string) {
  if (text === "Un-validated")
    return { bgcolor: "info.main", color: "info.contrastText" };
  if (text.includes("Error"))
    return { bgcolor: "error.main", color: "background.paper" };
  return { bgcolor: "success.main", color: "background.paper" };
}

export const UploadDialog: React.FC<UploadDialogProps> = (
  props: UploadDialogProps,
) => {
  const [filename, setFilename] = useState("");
  const [testListText, setTestListText] = useState("");

  // TODO: Refactor fileList to use parent props instead of local states.
  const [fileList, setFileList] = useState<FileObject[]>([]);
  const { validationText } = useFileEndpoint(fileList);
  const validationTextStyle = getValidationTextStyle(validationText);
  const { valid, statusText, parsedObject } = useJSONValidation(testListText);

  const handleClose = () => {
    if (validationText === "Save Success") {
      props.addFile(filename);
    }
    setFileList([]);
    setFilename("");
    setTestListText("");
    props.setCloseDialog();
  };
  const handleSave = () => {
    setFileList([{ filename: filename, data: parsedObject }]);
  };

  const handleFilenameChange = ({
    target: { value },
  }: React.ChangeEvent<HTMLInputElement>) => setFilename(value);

  const handleTextChange = ({
    target: { value },
  }: React.ChangeEvent<HTMLInputElement>) => {
    setTestListText(value);
  };

  return (
    <Dialog
      open={props.open}
      onClose={handleClose}
      maxWidth="lg"
      fullWidth={true}
    >
      <DialogTitle>{`${filename} test list`}</DialogTitle>
      <DialogContent>
        <DialogContentText>The test list name:</DialogContentText>
        <TextField
          autoFocus
          margin="dense"
          id="filename-text"
          name="filename-text"
          label="test list name"
          multiline
          fullWidth
          value={filename}
          onChange={handleFilenameChange}
        />
        <DialogContentText>
          Paste the content of the test list.
        </DialogContentText>
        <TextField
          error={!valid}
          helperText={statusText}
          autoFocus
          margin="dense"
          id="content-text"
          label="test list content"
          multiline
          fullWidth
          value={testListText}
          onChange={handleTextChange}
        />
        <DialogContentText>The parsed {filename} test list:</DialogContentText>
        <Typography variant="body1">
          {JSON.stringify(parsedObject, null, 2)}
        </Typography>
        <DialogContentText>
          Save status of {filename} test list:
        </DialogContentText>
        <Box sx={{ ...validationTextStyle }}>
          <Typography>{validationText}</Typography>
        </Box>
      </DialogContent>
      <DialogActions>
        <Button
          onClick={handleSave}
          color="info"
          variant="contained"
        >
          Save
        </Button>
        <Button
          onClick={handleClose}
          color="primary"
        >
          Close
        </Button>
      </DialogActions>
    </Dialog>
  );
};
