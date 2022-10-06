// Copyright 2018 The ChromiumOS Authors
// Use of this source code is governed by a BSD-style license that can be
// found in the LICENSE file.

export interface UpdateFactoryDriveRequest {
  project: string;
  id: number | null;
  dirId: number | null;
  name: string;
  file: File;
}

export interface UpdateFactoryDriveFormPayload {
  id: number | null;
  dirId: number | null;
  name: string;
  multiple: boolean;
}

export interface UpdateFactoryDriveVersionRequest {
  id: number;
  name: string;
  usingVer: number;
}

export interface RenameRequest {
  id: number;
  name: string;
}

export interface FactoryDrive {
  id: number;
  dirId: number | null;
  name: string;
  usingVer: number;
  revisions: string[];
}

export interface FactoryDriveDirectory {
  id: number;
  parentId: number | null;
  name: string;
}

export interface CreateDirectoryRequest {
  name: string;
  parentId: number | null;
}
