// Copyright 2023 The ChromiumOS Authors
// Use of this source code is governed by a BSD-style license that can be
// found in the LICENSE file.

import { useEffect, useState } from "react";

type JSONObject = { [key: string]: unknown };
export interface JSONValidation {
  valid: boolean;
  statusText: string;
  parsedObject: JSONObject;
}

export function useJSONValidation(value: string): JSONValidation {
  const [valid, setValid] = useState<boolean>(false);
  const [statusText, setStatusText] = useState<string>("");
  const [parsedObject, setParsedObject] = useState<JSONObject>({});
  useEffect(() => {
    try {
      setParsedObject(JSON.parse(value) as JSONObject);
      setValid(true);
      setStatusText("");
    } catch (error) {
      setParsedObject({});
      setStatusText("Invalid object");
      setValid(false);
    }
  }, [value]);
  return { valid, statusText, parsedObject };
}
