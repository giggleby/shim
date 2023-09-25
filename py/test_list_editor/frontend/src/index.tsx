// Copyright 2023 The ChromiumOS Authors
// Use of this source code is governed by a BSD-style license that can be
// found in the LICENSE file.

import React from "react";
import ReactDOM from "react-dom/client";
import { createBrowserRouter, RouterProvider } from "react-router-dom";
import { EditEmptyItemConfigPanel } from "./components/edit_empty_item_config_panel";
import { EditEmptyPanel } from "./components/edit_empty_panel";
import { EditItemConfigPanel } from "./components/edit_item_config_panel";
import { EditMainPanel } from "./components/edit_main_panel";
import "./index.css";
import { Edit } from "./pages/edit";
import { ErrorPage } from "./pages/error";
import { Landing } from "./pages/landing";
import { Upload } from "./pages/upload";

// TODO: Move router to a separate browser.ts
const router = createBrowserRouter([
  {
    path: "/",
    element: <Landing />,
    errorElement: <ErrorPage />,
  },
  {
    path: "/upload",
    element: <Upload />,
    errorElement: <ErrorPage />,
  },
  {
    path: "/edit",
    element: <Edit />,
    errorElement: <ErrorPage />,
    children: [
      {
        index: true,
        element: <EditEmptyPanel />,
      },
      {
        path: ":testListId",
        element: <EditMainPanel />,
        children: [
          {
            index: true,
            element: <EditEmptyItemConfigPanel />,
          },
          {
            path: ":testItemId",
            element: <EditItemConfigPanel />,
          },
        ],
      },
    ],
  },
]);

const root = ReactDOM.createRoot(
  document.getElementById("root") as HTMLElement,
);
root.render(
  <React.StrictMode>
    <RouterProvider router={router} />
  </React.StrictMode>,
);
