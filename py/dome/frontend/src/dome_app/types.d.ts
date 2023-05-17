// Copyright 2018 The ChromiumOS Authors
// Use of this source code is governed by a BSD-style license that can be
// found in the LICENSE file.

export type AppName =
  'PROJECTS_APP' |
  'BUNDLES_APP' |
  'CONFIG_APP' |
  'DASHBOARD_APP' |
  'FACTORY_DRIVE_APP' |
  'LOG_APP' |
  'SYNC_STATUS_APP';

export interface DomeInfo {
  dockerImageGithash: string;
  dockerImageIslocal: boolean;
  dockerImageTimestamp: string;
  dockerImageLatestVersion: string;
  isDevServer: boolean;
}
