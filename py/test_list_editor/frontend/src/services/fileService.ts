// Copyright 2023 The ChromiumOS Authors
// Use of this source code is governed by a BSD-style license that can be
// found in the LICENSE file.

import { BaseResponse } from "../interfaces/common";
import { BaseService, ValidationError } from "./common";

export interface FileObject {
  filename: string;
  data: { [key: string]: unknown };
}

// TODO: Include session_id
export interface FileData {
  files: FileObject[];
}

export interface FileValidationResponse extends BaseResponse {
  file_status: { [key: string]: BaseResponse };
}

export class FileService extends BaseService {
  private apiEndpoint = "/api/v1/files/";

  public async sendFiles(files: FileObject[]): Promise<FileValidationResponse> {
    const endpoint = new URL(this.apiEndpoint, this.backendURL);
    const data: FileData = {
      files: files,
    };
    const options = {
      body: JSON.stringify(data),
    };
    try {
      const response = await this.put<FileValidationResponse>(
        endpoint,
        options,
      );
      return response;
    } catch (error) {
      if (error instanceof ValidationError) {
        const body: BaseResponse =
          await (error.response.json() as Promise<BaseResponse>);
        return {
          file_status: {},
          ...body,
        };
      } else {
        console.error(error);
        throw error;
      }
    }
  }
}

export const fileService = new FileService();
