// Copyright 2018 The Chromium OS Authors. All rights reserved.
// Use of this source code is governed by a BSD-style license that can be
// found in the LICENSE file.

export interface UmpireSetting {
  umpireEnabled: boolean;
  umpireAddExistingOne: boolean;
  umpireHost: string | null;
  umpirePort: number | null;
  netbootBundle: string | null;
}

export interface UmpireServerResponse {
  name: string;
  isUmpireRecent: boolean;
  umpireEnabled: boolean;
  umpireHost: string | null;
  umpirePort: number | null;
  umpireVersion: number | null;
  netbootBundle: string | null;
}

export interface Project extends UmpireSetting, UmpireServerResponse {
  umpireReady: boolean;
}

export interface ProjectMap {
  [name: string]: Project;
}
