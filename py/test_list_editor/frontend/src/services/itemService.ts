// Copyright 2023 The ChromiumOS Authors
// Use of this source code is governed by a BSD-style license that can be
// found in the LICENSE file.

import { BaseResponse } from "../interfaces/common";
import { BaseService } from "./common";

// TODO(louischiu): Make optional fields required.

/** Interface for a single test item. */
export interface TestItem {
  test_item_id?: string;
  display_name?: string;
  inherit?: string;
  last_modified?: string;
  pytest_name?: string;
  run_if?: string;
  action_on_failure?: string;
  allow_reboot?: boolean;
  disable_abort?: boolean;
  parallel?: boolean;
  args?: string | object;
  locals?: string | object;
  disable_services?: string | object;
}

export interface TestItemResponse extends BaseResponse {
  data: TestItem;
}

/** Interface of a test item for display purpose. */
export interface TestItemDisplay {
  test_item_id: string;
  display_name: string;
  subtests: string[];
}

export interface TestItemDisplayDictResponse {
  [key: string]: TestItemDisplay;
}

export interface ItemListResponse extends BaseResponse {
  data: TestItemDisplayDictResponse;
}

/** Service class to make requests to the backend `/items` endpoint. */
export class ItemService extends BaseService {
  private readonly apiBaseEndpoint = "/api/v1/items/";
  testListId: string;
  endpoint: URL;

  constructor(testListId: string) {
    super();
    this.testListId = testListId;
    const apiEndpoint = `${this.apiBaseEndpoint}${this.testListId}`;
    this.endpoint = new URL(apiEndpoint, this.backendURL);
  }

  public async getItemList(): Promise<ItemListResponse> {
    const options = {};
    const response = await this.get<ItemListResponse>(this.endpoint, options);
    return response;
  }

  public async getTestItem(testItemId: string): Promise<TestItemResponse> {
    const apiEndpoint = `${this.apiBaseEndpoint}${this.testListId}/${testItemId}`;
    const endpoint = new URL(apiEndpoint, this.backendURL);
    const options = {};
    const response = await this.get<TestItemResponse>(endpoint, options);
    return response;
  }

  public async updateTestItem(testItem: TestItem): Promise<TestItemResponse> {
    const payload = {
      data: testItem,
    };
    const options = {
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    };
    const response = await this.put<TestItemResponse>(this.endpoint, options);
    return response;
  }

  public async createTestItem(testItem: TestItem): Promise<TestItemResponse> {
    const payload = {
      data: testItem,
    };
    const options = {
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    };
    const response = await this.post<TestItemResponse>(this.endpoint, options);
    return response;
  }
}

interface param {
  testListId?: string;
  testItemId?: string;
  [key: string]: unknown;
}

/** Interface for the router loader. */
interface loaderParams {
  params: param;
}

/** Interface for sharing data between router loader and components. */
export interface TestItemLoaderResponse {
  testItemData: TestItem;
  testItemId: string;
}

/** Exception to raise when parameters are undefined. */
export class ParamsUndefined extends Error {}

/** Test item loader function.
 *
 * This function is for react router to make request when we visit
 * `/edit/:test_list_id/:test_item_id`.
 */
export const getTestItemConfig = async ({
  params,
}: loaderParams): Promise<TestItemLoaderResponse> => {
  if (!params.testListId || !params.testItemId) {
    throw new ParamsUndefined("Test list id and test item id are not defined.");
  }
  const itemService = new ItemService(params.testListId);
  const response = await itemService.getTestItem(params.testItemId);
  const testItemData = response.data;
  return {
    testItemId: params.testItemId,
    testItemData: testItemData,
  };
};
