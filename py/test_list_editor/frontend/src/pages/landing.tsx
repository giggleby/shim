// Copyright 2023 The ChromiumOS Authors
// Use of this source code is governed by a BSD-style license that can be
// found in the LICENSE file.

import { LandingHeader } from "../components/landing_header";
import { SearchBar } from "../components/search_bar";
import { SessionIdFloater } from "../components/session_id_display";

export function Landing() {
  return (
    <div>
      <SessionIdFloater />
      <SearchBar />
      <LandingHeader />
    </div>
  );
}
