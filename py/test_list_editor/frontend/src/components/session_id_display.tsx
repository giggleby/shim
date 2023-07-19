// Copyright 2023 The ChromiumOS Authors
// Use of this source code is governed by a BSD-style license that can be
// found in the LICENSE file.

import { useSessionId } from "../hooks/session_id";

export function SessionIdFloater() {
  const sessionId = useSessionId();
  return (
    <div>
      <span
        style={{
          position: "absolute",
          top: 0,
          right: 0,
          zIndex: 3100,
          color: "lightgray",
        }}
      >
        Session: {sessionId}
      </span>
    </div>
  );
}
