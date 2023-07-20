// Copyright 2023 The ChromiumOS Authors
// Use of this source code is governed by a BSD-style license that can be
// found in the LICENSE file.

import { useEffect, useState } from "react";
import {
  FileObject,
  FileService,
  FileValidationResponse,
} from "../services/fileService";

// TODO: Display better error text. Make sure it doesn't show "data [0] -> is missing field xxx
// which is required".

export function useFileEndpoint(fileList: FileObject[]) {
  const [validationText, setValidationText] = useState<string>("Un-validated");
  const fileService = new FileService();

  useEffect(() => {
    async function sendFiles() {
      const response: FileValidationResponse = await fileService.sendFiles(
        fileList,
      );
      if (response.status === "success") {
        setValidationText("Save Success");
      } else if (response.status === "validation_error") {
        setValidationText(`Validation Error: ${response.message}`);
      } else {
        setValidationText(
          `Unknown Error: ${response.status}, ${response.message}`,
        );
      }
    }
    if (fileList.length !== 0) {
      void sendFiles();
    } else {
      setValidationText("Un-validated");
    }

    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [fileList]);

  return { validationText };
}
