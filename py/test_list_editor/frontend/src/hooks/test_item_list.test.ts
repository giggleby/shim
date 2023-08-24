// Copyright 2023 The ChromiumOS Authors
// Use of this source code is governed by a BSD-style license that can be
// found in the LICENSE file.

import { renderHook, waitFor } from "@testing-library/react";
import { TestItemListResult, useTestItemList } from "./test_item_list";

import { Status } from "../interfaces/common";
import {
  ItemService,
  TestItemDisplayDictResponse,
} from "../services/itemService";

describe("Test TestItemList hook", () => {
  const spyGet = jest.spyOn(ItemService.prototype, "getItemList");
  const fakeItemServiceResponse = {
    status: Status.SUCCESS,
    data: {},
    message: "",
  };
  beforeEach(() => {
    spyGet.mockReset();

    fakeItemServiceResponse.data = {};

    spyGet.mockResolvedValue(fakeItemServiceResponse);
  });
  test("Returns a list of test items", async () => {
    const itemList: TestItemDisplayDictResponse = {
      ABC: {
        test_item_id: "ABC",
        display_name: "ABC",
        subtests: [],
      },
    };
    fakeItemServiceResponse.data = itemList;
    const { result } = renderHook(() => useTestItemList("fake.test_list"));

    await waitFor(() => {
      const hookResult: TestItemListResult = result.current;
      expect(hookResult.testItemList).toStrictEqual(["ABC"]);
    });
  });

  test("Returns no test item", async () => {
    const { result } = renderHook(() => useTestItemList("fake.test_list"));

    await waitFor(() => {
      const hookResult: TestItemListResult = result.current;
      expect(hookResult.testItemList).toStrictEqual([]);
    });
  });
});
