// Copyright 2023 The ChromiumOS Authors
// Use of this source code is governed by a BSD-style license that can be
// found in the LICENSE file.

// TODO: setup a mechanism for using different endpoints
// based on the config (dev, staging, prod).
export const backendURL = "http://localhost:5000";

export class ValidationError extends Error {
  public response: Response;

  constructor(message: string, response: Response) {
    super(message);
    this.name = "ValidationError";
    this.response = response;
  }
}

function responseHandler<T>(response: Response): Promise<T> {
  if (response.ok) {
    return response.json() as Promise<T>;
  }
  if (response.status === 422) {
    throw new ValidationError("Some fields are incorrect", response);
  }
  throw new Error(response.statusText);
}

export abstract class BaseService {
  protected backendURL: string;
  protected baseOptions: RequestInit;

  constructor() {
    this.backendURL = backendURL;
    // TODO: Add a timeout handler
    this.baseOptions = {};
  }

  protected async get<T>(endpoint: URL, options: object = {}): Promise<T> {
    this.baseOptions.method = "GET";
    const requestOptions = { ...this.baseOptions, ...options };
    const response = await fetch(endpoint, requestOptions);
    return responseHandler<T>(response);
  }

  protected async put<T>(endpoint: URL, options: object = {}): Promise<T> {
    this.baseOptions.method = "PUT";
    this.baseOptions.headers = {
      "Content-Type": "application/json",
    };
    const requestOptions = { ...this.baseOptions, ...options };
    const response = await fetch(endpoint, requestOptions);
    return responseHandler<T>(response);
  }

  protected async post<T>(endpoint: URL, options: object = {}): Promise<T> {
    this.baseOptions.method = "POST";
    this.baseOptions.headers = {
      "Content-Type": "application/json",
    };
    const requestOptions = { ...this.baseOptions, ...options };
    const response = await fetch(endpoint, requestOptions);
    return responseHandler<T>(response);
  }
}
