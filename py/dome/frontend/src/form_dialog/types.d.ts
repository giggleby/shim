// Copyright 2018 The ChromiumOS Authors
// Use of this source code is governed by a BSD-style license that can be
// found in the LICENSE file.

import bundle from '@app/bundle';
import {UpdateResourceFormPayload} from '@app/bundle/types';
import dashboard from '@app/dashboard';
import factoryDrive from '@app/factory_drives';
import {
  UpdateFactoryDriveFormPayload,
  RenameRequest,
} from '@app/factory_drives/types';

import {Unionize} from '@common/types';

export interface FormPayloadTypeMap {
  [dashboard.constants.ENABLE_UMPIRE_FORM]: {};
  [bundle.constants.UPLOAD_BUNDLE_FORM]: {};
  [bundle.constants.UPDATE_RESOURCE_FORM]: UpdateResourceFormPayload;
  [factoryDrive.constants.UPDATE_FACTORY_DRIVE_FORM]: UpdateFactoryDriveFormPayload;
  [factoryDrive.constants.CREATE_DIRECTORY_FORM]: {};
  [factoryDrive.constants.RENAME_DIRECTORY_FORM]: RenameRequest;
  [factoryDrive.constants.RENAME_FACTORY_DRIVE_FORM]: RenameRequest;
}

export type FormNames = keyof FormPayloadTypeMap;

export type FormDataType = Unionize<{
  [K in FormNames]: {formName: K} & {formPayload: FormPayloadTypeMap[K]};
}>;
