// Copyright 2023 The ChromiumOS Authors
// Use of this source code is governed by a BSD-style license that can be
// found in the LICENSE file.

import { renderHook, waitFor } from "@testing-library/react";
import { Status } from "../interfaces/common";
import { FileObject, FileService } from "../services/fileService";
import { useFileEndpoint } from "./file";

describe("Test useFileEndpoint", () => {
  test("Call API when the list has item", async () => {
    jest.spyOn(FileService.prototype, "sendFiles").mockResolvedValue({
      status: Status.SUCCESS,
      file_status: {},
      message: "",
    });
    const fakeFileObjects: FileObject[] = [
      {
        filename: "abc",
        data: {},
      },
    ];
    const { result } = renderHook(useFileEndpoint, {
      initialProps: fakeFileObjects,
    });
    await waitFor(() =>
      expect(result.current.validationText).toBe("Save Success"),
    );
  });
  test("Don't call API when the list is empty", async () => {
    const fakeFileObjects: FileObject[] = [];
    const { result } = renderHook(useFileEndpoint, {
      initialProps: fakeFileObjects,
    });
    await waitFor(() =>
      expect(result.current.validationText).toBe("Un-validated"),
    );
  });
  test("Validation error", async () => {
    jest.spyOn(FileService.prototype, "sendFiles").mockResolvedValue({
      status: Status.VALIDATION_ERROR,
      file_status: {},
      message: "321",
    });
    const fakeFileObjects: FileObject[] = [
      {
        filename: "abc",
        data: {},
      },
    ];
    const { result } = renderHook(useFileEndpoint, {
      initialProps: fakeFileObjects,
    });
    await waitFor(() =>
      expect(result.current.validationText).toBe("Validation Error: 321"),
    );
  });
  test("Unknown error", async () => {
    jest.spyOn(FileService.prototype, "sendFiles").mockResolvedValue({
      status: Status.ERROR,
      file_status: {},
      message: "unknown",
    });
    const fakeFileObjects: FileObject[] = [
      {
        filename: "abc",
        data: {},
      },
    ];
    const { result } = renderHook(useFileEndpoint, {
      initialProps: fakeFileObjects,
    });
    await waitFor(() =>
      expect(result.current.validationText).toBe(
        "Unknown Error: error, unknown",
      ),
    );
  });
});
