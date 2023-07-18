// Copyright 2023 The ChromiumOS Authors
// Use of this source code is governed by a BSD-style license that can be
// found in the LICENSE file.

import React from "react";
import ReactDOM from "react-dom/client";
import "./index.css";

if (!document.getElementById("root")) {
  const div = document.createElement("div");
  div.id = "root";
  document.body.appendChild(div);
}
export const root = ReactDOM.createRoot(
  document.getElementById("root") as HTMLElement,
);
root.render(
  <React.StrictMode>
    <div></div>
  </React.StrictMode>,
);
