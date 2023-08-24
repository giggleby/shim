// Copyright 2023 The ChromiumOS Authors
// Use of this source code is governed by a BSD-style license that can be
// found in the LICENSE file.

import { renderHook, waitFor } from "@testing-library/react";
import { TestItemHookResult, useTestItem } from "./test_item";

import { Status } from "../interfaces/common";
import { ItemService, TestItem } from "../services/itemService";

describe("Test TestItem hook", () => {
  const spy = jest.spyOn(ItemService.prototype, "getTestItem");
  const spyUpdate = jest.spyOn(ItemService.prototype, "updateTestItem");
  const fakeGetResponse = {
    status: Status.SUCCESS,
    data: {},
    message: "",
  };
  const fakeUpdateResponse = {
    status: Status.SUCCESS,
    data: {},
    message: "",
  };
  const items: TestItem = {
    test_item_id: "ABC",
    display_name: "ABC",
  };
  const newItem: TestItem = {
    test_item_id: "ABC",
    display_name: "NewA",
  };
  beforeEach(() => {
    spy.mockReset();
    spyUpdate.mockReset();

    fakeGetResponse.data = {};
    fakeUpdateResponse.data = {};

    spy.mockResolvedValue(fakeGetResponse);
    spyUpdate.mockResolvedValue(fakeUpdateResponse);
  });

  test("Returns a test item", () => {
    const { result } = renderHook(() => useTestItem("fake.test_list", items));
    const hookResult: TestItemHookResult = result.current;
    expect(hookResult.testItem).toStrictEqual(items);
  });

  test("Convert object field of a test item.", () => {
    const fakeItem = { args: { some_field: true } };
    const expectedOutput = JSON.stringify(fakeItem.args, null, 2);
    const { result } = renderHook(() =>
      useTestItem("fake.test_list", fakeItem),
    );
    const hookResult: TestItemHookResult = result.current;
    expect(hookResult.testItem.args).toStrictEqual(expectedOutput);
  });

  test("Don't convert object field if type not match", () => {
    const fakeItem = { args: '{\n  "some_field": true\n}' };
    const expectedOutput = '{\n  "some_field": true\n}';
    const { result } = renderHook(() =>
      useTestItem("fake.test_list", fakeItem),
    );
    const hookResult: TestItemHookResult = result.current;
    expect(hookResult.testItem.args).toStrictEqual(expectedOutput);
  });

  test("Update test item filed", async () => {
    const { result } = renderHook(() => useTestItem("fake.test_list", items));

    let hookResult: TestItemHookResult = result.current;
    await waitFor(() => {
      hookResult.updateField("test_item_id", "Modified ABC");
    });

    hookResult = result.current;
    expect(hookResult.testItem).toStrictEqual({
      ...items,
      test_item_id: "Modified ABC",
    });
  });

  test("Call updateTestItem and expect updated test item", async () => {
    fakeUpdateResponse.data = newItem;
    const { result } = renderHook(() => useTestItem("fake.test_list", items));

    let hookResult: TestItemHookResult = result.current;
    await waitFor(async () => {
      await hookResult.updateTestItem();
    });
    expect(spyUpdate).toBeCalledTimes(1);

    hookResult = result.current;
    expect(hookResult.testItem).toStrictEqual(newItem);
  });
});
