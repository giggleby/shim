// Copyright 2023 The ChromiumOS Authors
// Use of this source code is governed by a BSD-style license that can be
// found in the LICENSE file.

import { useEffect, useState } from "react";
import { ItemService } from "../services/itemService";

/** The object that holds a list of test items. */
export interface TestItemListResult {
  testItemList: string[];
}

/**
 * Custom hook to fetch and manage a list of test items.
 * @param {string} testListId - The ID of the test list.
 * @returns {TestItemListResult} An object containing the test item list.
 */
export function useTestItemList(testListId: string): TestItemListResult {
  // The empty list defaults to "FactoryTest" because it is the base
  // class of all test item and it must exist.
  const [testItemList, setTestItemList] = useState<string[]>(["FactoryTest"]);
  const itemService = new ItemService(testListId);

  useEffect(() => {
    async function getItemList() {
      const testItems = await itemService.getItemList();
      const itemLists: string[] = [];
      Object.entries(testItems.data).forEach(([_, value]) => {
        itemLists.push(value.test_item_id);
      });
      setTestItemList(itemLists);
    }
    void getItemList();

    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [testListId]);

  return { testItemList };
}
