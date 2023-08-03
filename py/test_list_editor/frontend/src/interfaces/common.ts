// Copyright 2023 The ChromiumOS Authors
// Use of this source code is governed by a BSD-style license that can be
// found in the LICENSE file.

export enum Status {
  SUCCESS = "success",
  VALIDATION_ERROR = "validation_error",
  ERROR = "error",
}

export interface BaseResponse {
  status: Status;
  message: string;
}
