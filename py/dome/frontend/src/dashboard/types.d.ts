// Copyright 2018 The Chromium OS Authors. All rights reserved.
// Use of this source code is governed by a BSD-style license that can be
// found in the LICENSE file.

export interface PortResponse {
  allPorts: Port[];
  maxPortOffset: number;
}

export interface Port extends PortResponse {
  name: string;
  umpirePort: number;
}
