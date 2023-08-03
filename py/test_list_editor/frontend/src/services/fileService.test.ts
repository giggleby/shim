// Copyright 2023 The ChromiumOS Authors
// Use of this source code is governed by a BSD-style license that can be
// found in the LICENSE file.

import "@testing-library/jest-dom";
import { Status } from "../interfaces/common";
import { FileObject, FileService, FileValidationResponse } from "./fileService";

describe("File service testing", () => {
  test("put", async () => {
    const fakeResponse: FileValidationResponse = {
      status: Status.SUCCESS,
      message: "",
      file_status: {
        test1: {
          status: Status.SUCCESS,
          message: "",
        },
      },
    };

    global.fetch = jest.fn().mockResolvedValue({
      ok: jest.fn().mockReturnValue(true),
      json: jest.fn().mockResolvedValue(fakeResponse),
    });

    const fakeData: FileObject[] = [
      {
        filename: "abc",
        data: {
          some_field: true,
        },
      },
    ];
    const fileService = new FileService();
    const response: FileValidationResponse = await fileService.sendFiles(
      fakeData,
    );
    expect(response).toStrictEqual(fakeResponse);
  });
  test("validation error", async () => {
    const fakeResponse: FileValidationResponse = {
      status: Status.VALIDATION_ERROR,
      message: "",
      file_status: {},
    };

    global.fetch = jest.fn().mockResolvedValue({
      ok: false,
      status: 422,
      json: jest.fn().mockResolvedValue(fakeResponse),
    });

    const fakeData: FileObject[] = [
      {
        filename: "abc",
        data: {
          some_field: true,
        },
      },
    ];
    const fileService = new FileService();
    const response: FileValidationResponse = await fileService.sendFiles(
      fakeData,
    );
    expect(response).toStrictEqual(fakeResponse);
  });
  test("unknown error", async () => {
    const fakeResponse: FileValidationResponse = {
      status: Status.ERROR,
      message: "",
      file_status: {},
    };

    global.fetch = jest.fn().mockResolvedValue({
      ok: false,
      status: 500,
      json: jest.fn().mockResolvedValue(fakeResponse),
    });
    global.console.error = jest.fn();

    const fakeData: FileObject[] = [
      {
        filename: "abc",
        data: {
          some_field: true,
        },
      },
    ];
    const fileService = new FileService();
    const target = async () => await fileService.sendFiles(fakeData);
    await expect(target).rejects.toThrow();
  });
});
