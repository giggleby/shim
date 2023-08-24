// Copyright 2023 The ChromiumOS Authors
// Use of this source code is governed by a BSD-style license that can be
// found in the LICENSE file.

import { useState } from "react";
import { ItemService, TestItem } from "../services/itemService";

const objectFields = ["args", "locals", "disable_services"];

type testItemKeyType = keyof TestItem;

/**
 * Converts defined object field in `TestItem` to string field.
 *
 * The function converts predefined attributes in `objectFields` of the passed in
 * test item to string format.
 */
function _convertObjectToString(obj: TestItem): void {
  objectFields.forEach((val) => {
    if (Object.prototype.hasOwnProperty.call(obj, val)) {
      const key = val as testItemKeyType;
      if (typeof obj[key] === "object") {
        (obj[key] as string) = JSON.stringify(obj[key], null, 2);
      }
    }
  });
  return;
}

/**
 * Result of the `TestItemHook`
 *
 * Use `updateField` to update a field of the test item the hook is managing.
 * Use `updateTestItem` to propagate the change in the frontend to the backend.
 */
export interface TestItemHookResult {
  testItem: TestItem;
  /**
   * Updates the field of a `testItem` with `data`.
   *
   * This function updates the React state of the test item. It does not update
   * the state of the backend test item. To update the state of the backend item,
   * use `updateTestItem` instead.
   * @param field keyof the `TestItem`.
   * @param data the value to update the test item.
   * @returns {void}
   */
  updateField: (field: keyof TestItem, data: string | boolean | object) => void;

  /**
   * Update the test item in the backend to be the same as the frontend.
   * @returns {Promise<void>}
   */
  updateTestItem: () => Promise<void>;
}

/**
 * Custom hook to manage a test item.
 *
 * @param {string} testListId - The ID of the test list to which the test item belongs.
 * @param {TestItem} testItemData - The ID of the test item to manage.
 * @returns {TestItemHookResult} An object containing the test item and a function to update it.
 */
export function useTestItem(
  testListId: string,
  testItemData: TestItem,
): TestItemHookResult {
  _convertObjectToString(testItemData);

  const [testItem, setTestItem] = useState<TestItem>(testItemData);
  const itemService = new ItemService(testListId);

  function updateField(field: keyof TestItem, data: string | boolean | object) {
    setTestItem({
      ...testItem,
      [field]: data,
    });
  }

  async function updateTestItem() {
    const response = await itemService.updateTestItem(testItem);
    setTestItem(response.data);
  }

  return { testItem, updateField, updateTestItem };
}
