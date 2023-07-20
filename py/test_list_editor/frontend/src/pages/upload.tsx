// Copyright 2023 The ChromiumOS Authors
// Use of this source code is governed by a BSD-style license that can be
// found in the LICENSE file.

import { SearchBar } from "../components/search_bar";
import { SessionIdFloater } from "../components/session_id_display";
import { UploadFileTable } from "../components/upload_file_table";
import { UploadHeader } from "../components/upload_header";

export function Upload() {
  return (
    <div>
      <SessionIdFloater />
      <SearchBar />
      <UploadHeader />
      <UploadFileTable />
    </div>
  );
}
