// Copyright 2023 The ChromiumOS Authors
// Use of this source code is governed by a BSD-style license that can be
// found in the LICENSE file.

import "@testing-library/jest-dom";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { FileService } from "../services/fileService";
import { UploadDialog } from "./upload_dialog";

jest.mock("../services/fileService", () => ({
  FileService: jest.fn(),
}));

describe("Upload Dialog Test", () => {
  test("renders correctly", () => {
    render(
      <UploadDialog
        open={true}
        setCloseDialog={jest.fn()}
        addFile={jest.fn()}
      />,
    );

    const validateButton = screen.getByRole("button", { name: "Save" });
    expect(validateButton).toBeInTheDocument();
  });
  test("renders title", async () => {
    const user = userEvent.setup();
    render(
      <UploadDialog
        open={true}
        setCloseDialog={jest.fn()}
        addFile={jest.fn()}
      />,
    );

    const filenameArea = screen.getByRole("textbox", {
      name: /^test list name/i,
    });
    await user.type(filenameArea, "main_xxx");
    expect(filenameArea).toHaveValue("main_xxx");

    const titleText = screen.getByRole("heading", {
      name: /main_xxx test list/i,
    });
    expect(titleText).toBeInTheDocument();
  });
  test("Doesn't render incorrect test list", async () => {
    const user = userEvent.setup();
    render(
      <UploadDialog
        open={true}
        setCloseDialog={jest.fn()}
        addFile={jest.fn()}
      />,
    );
    const contentArea = screen.getByLabelText(/test list content/i);
    await user.type(contentArea, '{{ "something": }');

    const testListParsed = screen.getByText("{}");
    expect(testListParsed).toBeInTheDocument();
  });

  test("Renders correct test list", async () => {
    const user = userEvent.setup();
    render(
      <UploadDialog
        open={true}
        setCloseDialog={jest.fn()}
        addFile={jest.fn()}
      />,
    );
    const contentArea = screen.getByLabelText(/test list content/i);
    await user.type(contentArea, '{{ "something": 123}');

    const testListParsed = screen.queryAllByText(/"something": 123/);
    expect(testListParsed).toHaveLength(2);
  });

  test("Close un-validated test list and won't save", async () => {
    const user = userEvent.setup();
    const closeHandler = jest.fn();
    const addFileHandler = jest.fn();
    render(
      <UploadDialog
        open={true}
        setCloseDialog={closeHandler}
        addFile={addFileHandler}
      />,
    );
    const closeButton = screen.getByRole("button", { name: "Close" });
    await user.click(closeButton);

    expect(closeHandler).toBeCalled();
    expect(addFileHandler).toBeCalledTimes(0);
  });

  test("Click save button can trigger mock api calls.", async () => {
    const mockSendFiles = jest.fn().mockResolvedValue({
      status: "success",
    });
    FileService.prototype.sendFiles = mockSendFiles;
    const user = userEvent.setup();
    render(
      <UploadDialog
        open={true}
        setCloseDialog={jest.fn()}
        addFile={jest.fn()}
      />,
    );

    const validateButton = screen.getByRole("button", { name: "Save" });
    await user.click(validateButton);

    expect(mockSendFiles).toHaveBeenCalled();

    const validationText = screen.queryByText(/Save Success/);
    expect(validationText).toBeInTheDocument();
  });

  test("API returns validation error, renders validation_error", async () => {
    const mockSendFiles = jest.fn().mockResolvedValue({
      status: "validation_error",
    });
    FileService.prototype.sendFiles = mockSendFiles;

    const user = userEvent.setup();
    render(
      <UploadDialog
        open={true}
        setCloseDialog={jest.fn()}
        addFile={jest.fn()}
      />,
    );

    const validateButton = screen.getByRole("button", { name: "Save" });
    await user.click(validateButton);

    expect(mockSendFiles).toHaveBeenCalled();

    const validationText = screen.queryByText(/Validation Error/i);
    expect(validationText).toBeInTheDocument();
  });

  test("Close validated test list will show the validated test list", async () => {
    FileService.prototype.sendFiles = jest.fn().mockResolvedValue({
      status: "success",
    });
    const user = userEvent.setup();
    const closeHandler = jest.fn();
    const addFileHandler = jest.fn();
    render(
      <UploadDialog
        open={true}
        setCloseDialog={closeHandler}
        addFile={addFileHandler}
      />,
    );
    const validateButton = screen.getByRole("button", { name: "Save" });
    await user.click(validateButton);
    const closeButton = screen.getByRole("button", { name: "Close" });
    await user.click(closeButton);

    expect(closeHandler).toBeCalled();
    expect(addFileHandler).toBeCalled();
  });
});
