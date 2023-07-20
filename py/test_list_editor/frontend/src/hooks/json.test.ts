// Copyright 2023 The ChromiumOS Authors
// Use of this source code is governed by a BSD-style license that can be
// found in the LICENSE file.

import { renderHook } from "@testing-library/react";
import { useJSONValidation } from "./json";

type JSONObject = { [key: string]: unknown };
export interface JSONValidation {
  valid: boolean;
  statusText: string;
  parsedObject: JSONObject;
}

describe("Test useJSONValidation", () => {
  test("validate a correctly formed JSON string", () => {
    const validString = '{"abc": true}';
    const { result } = renderHook(useJSONValidation, {
      initialProps: validString,
    });

    expect(result.current.valid).toBe(true);
    expect(result.current.statusText).toBe("");
  });
  test("validate an incorrect JSON string", () => {
    const invalidString = '{"abc": FAULT}';
    const { result } = renderHook(useJSONValidation, {
      initialProps: invalidString,
    });

    expect(result.current.valid).toBe(false);
  });
});
