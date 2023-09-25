// Copyright 2023 The ChromiumOS Authors
// Use of this source code is governed by a BSD-style license that can be
// found in the LICENSE file.

import { Outlet } from "react-router-dom";
import { SearchBar } from "../components/search_bar";
import { SessionIdFloater } from "../components/session_id_display";

export function Edit() {
  return (
    <div>
      <SessionIdFloater />
      <SearchBar />
      <Outlet />
    </div>
  );
}
