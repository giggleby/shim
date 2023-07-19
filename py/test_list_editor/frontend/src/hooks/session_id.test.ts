// Copyright 2023 The ChromiumOS Authors
// Use of this source code is governed by a BSD-style license that can be
// found in the LICENSE file.

import { useSessionId } from "./session_id";

jest.mock("uuid", () => ({
  v4: () => "12345678",
}));

describe("Session Id Hook Test", () => {
  test("Returns Expected Session Id.", () => {
    expect(useSessionId()).toBe("12345678");
  });
  test("Returns Session Id.", () => {
    jest.spyOn(Storage.prototype, "getItem").mockReturnValue("123");
    const setItemSpy = jest.spyOn(Storage.prototype, "setItem");
    useSessionId();
    expect(setItemSpy).toBeCalledTimes(0);
  });
});
