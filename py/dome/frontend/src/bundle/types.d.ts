// Copyright 2018 The ChromiumOS Authors
// Use of this source code is governed by a BSD-style license that can be
// found in the LICENSE file.

export interface UpdateResourceFormPayload {
  bundleName: string;
  resourceKey: string;
  resourceType: string;
}

export interface UpdateResourceRequestPayload {
  project: string;
  name: string;
  newName: string;
  note: string;
  resources: {
    [resourceType: string]: {
      type: string;
      file: File;
    };
  };
}

export interface UploadBundleRequestPayload {
  project: string;
  name: string;
  note: string;
  bundleFile: File;
}

export interface Resource {
  type: string;
  version: string;
  hash: string;
  information: string;
  warningMessage: string;
}

export interface ResourceMap {
  [type: string]: Resource;
}

export interface FileList {
  file: string;
  version: string;
}

export interface RequireUserAction {
  type: string;
  fileList: FileList[];
}

export interface RequireUserActionMap {
  [type: string]: RequireUserAction[];
}

export interface Bundle {
  name: string;
  note: string;
  active: boolean;
  resources: ResourceMap;
  warningMessage: string;
  requireUserAction: RequireUserActionMap;
}

export interface DeletedResources {
  files: string[];
  size: number;
}