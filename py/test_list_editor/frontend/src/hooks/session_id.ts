// Copyright 2023 The ChromiumOS Authors
// Use of this source code is governed by a BSD-style license that can be
// found in the LICENSE file.

import { v4 as uuid } from "uuid";

const TOKEN_STRING = "editor_user_token";

export function useSessionId() {
  const token = localStorage.getItem(TOKEN_STRING);
  if (token === null) {
    localStorage.setItem(TOKEN_STRING, uuid());
  }
  return localStorage.getItem(TOKEN_STRING);
}
