// Copyright 2018 The Chromium OS Authors. All rights reserved.
// Use of this source code is governed by a BSD-style license that can be
// found in the LICENSE file.

import {createAction} from 'typesafe-actions';

import error from '@app/error';
import formDialog from '@app/form_dialog';
import project from '@app/project';
import task from '@app/task';
import {Dispatch, RootState} from '@app/types';

import {authorizedAxios, isAxiosError} from '@common/utils';

import {
  CREATE_DIRECTORY_FORM,
  RENAME_DIRECTORY_FORM,
  RENAME_FACTORY_DRIVE_FORM,
  UPDATE_FACTORY_DRIVE_FORM,
} from './constants';
import {getFactoryDriveDirs, getFactoryDrives} from './selector';
import {
  CreateDirectoryRequest,
  FactoryDrive,
  FactoryDriveDirectory,
  RenameRequest,
  UpdateFactoryDriveRequest,
  UpdateFactoryDriveVersionRequest,
} from './types';

const baseURL = (getState: () => RootState): string => {
  return `/projects/${project.selectors.getCurrentProject(getState())}`;
};

const receiveFactoryDrives = createAction('RECEIVE_FACTORY_DRIVES', (resolve) =>
  (factoryDrives: FactoryDrive[]) => resolve({factoryDrives}));

const receiveFactoryDriveDirs =
  createAction('RECEIVE_FACTORY_DRIVE_DIRS', (resolve) =>
  (factoryDriveDirs: FactoryDriveDirectory[]) => resolve({factoryDriveDirs}));

const updateFactoryDrive = createAction('UPDATE_FACTORY_DRIVE', (resolve) =>
  (factoryDrive: FactoryDrive) => resolve({factoryDrive}));

const updateFactoryDriveDir =
  createAction('UPDATE_FACTORY_DRIVE_DIR', (resolve) =>
  (factoryDriveDir: FactoryDriveDirectory) => resolve({factoryDriveDir}));

export const basicActions = {
  receiveFactoryDrives,
  updateFactoryDrive,
  receiveFactoryDriveDirs,
  updateFactoryDriveDir,
};

export const startCreateDirectory = (data: CreateDirectoryRequest) =>
  async (dispatch: Dispatch, getState: () => RootState) => {
    dispatch(formDialog.actions.closeForm(CREATE_DIRECTORY_FORM));

    const factoryDriveDirs = getFactoryDriveDirs(getState());
    const optimisticUpdate = () => {
      let newFactoryDriveDir = factoryDriveDirs.find((d) => (
        d.name === data.name && d.parentId === data.parentId));
      if (!newFactoryDriveDir) {
        newFactoryDriveDir = {
          id: factoryDriveDirs.length,
          name: data.name,
          parentId: data.parentId,
        };
      }
      dispatch(updateFactoryDriveDir(newFactoryDriveDir));
    };

    // send the request
    const description = `Create Directory "${data.name}"`;
    const factoryDriveDir =
      await dispatch(task.actions.runTask<FactoryDriveDirectory>(
        description, 'POST', `${baseURL(getState)}/factory_drives/dirs/`, data,
        optimisticUpdate));
    dispatch(updateFactoryDriveDir(factoryDriveDir));
  };

export const startUpdateFactoryDrive = (data: UpdateFactoryDriveRequest) =>
  async (dispatch: Dispatch, getState: () => RootState) => {
    dispatch(formDialog.actions.closeForm(UPDATE_FACTORY_DRIVE_FORM));

    const factoryDrives = getFactoryDrives(getState());
    const optimisticUpdate = () => {
      let newFactoryDrive = null;
      if (data.id == null) {
        newFactoryDrive = factoryDrives.find((p) => (
          p.name === data.name && p.dirId === data.dirId));
        if (!newFactoryDrive) {
          newFactoryDrive = {
            id: factoryDrives.length,
            dirId: data.dirId,
            name: data.name,
            usingVer: 0,
            revisions: [],
          };
        }
      } else {
        newFactoryDrive = factoryDrives[data.id];
      }
      dispatch(updateFactoryDrive(newFactoryDrive));
    };

    // send the request
    const description = `Update factory drive "${data.name}"`;
    const factoryDriveComponent = await dispatch(
      task.actions.runTask<FactoryDrive>(
      description, 'POST', `${baseURL(getState)}/factory_drives/files/`, data,
      optimisticUpdate));
    dispatch(updateFactoryDrive(factoryDriveComponent));
  };

export const startUpdateComponentVersion =
  (data: UpdateFactoryDriveVersionRequest) =>
    async (dispatch: Dispatch, getState: () => RootState) => {
      // send the request
      const description = `Update factory drive "${data.name}"  version`;
      const factoryDriveComponent = await dispatch(
        task.actions.runTask<FactoryDrive>(
        description, 'POST', `${baseURL(getState)}/factory_drives/files/`, data,
        () => {
          dispatch(updateFactoryDrive({
            ...getFactoryDrives(
              getState())[data.id],
              usingVer: data.usingVer,
          }));
        }));
      dispatch(updateFactoryDrive(factoryDriveComponent));
    };

export const startRenameFactoryDrive = (data: RenameRequest) =>
  async (dispatch: Dispatch, getState: () => RootState) => {
    dispatch(formDialog.actions.closeForm(RENAME_FACTORY_DRIVE_FORM));
    // send the request
    const description = `Rename factory drive "${data.name}"`;
    const factoryDriveComponent = await dispatch(
      task.actions.runTask<FactoryDrive>(
      description, 'POST', `${baseURL(getState)}/factory_drives/files/`, data,
      () => {
        dispatch(updateFactoryDrive({
          ...getFactoryDrives(
            getState())[data.id],
            name: data.name,
          }));
      }));
    dispatch(updateFactoryDrive(factoryDriveComponent));
  };

export const startRenameDirectory = (data: RenameRequest) =>
  async (dispatch: Dispatch, getState: () => RootState) => {
    dispatch(formDialog.actions.closeForm(RENAME_DIRECTORY_FORM));
    // send the request
    const description = `Rename directory "${data.name}"`;
    const directoryComponent =
      await dispatch(task.actions.runTask<FactoryDriveDirectory>(
        description, 'POST', `${baseURL(getState)}/factory_drives/dirs/`, data,
        () => {
          dispatch(updateFactoryDriveDir({
            ...getFactoryDriveDirs(getState())[data.id], name: data.name}));
        }));
    dispatch(updateFactoryDriveDir(directoryComponent));
  };

export const fetchFactoryDrives = () =>
  async (dispatch: Dispatch, getState: () => RootState) => {
    try {
      const components = await authorizedAxios().get<FactoryDrive[]>(
        `${baseURL(getState)}/factory_drives/files.json`);
      dispatch(receiveFactoryDrives(components.data));
      const directories = await authorizedAxios().get<FactoryDriveDirectory[]>(
        `${baseURL(getState)}/factory_drives/dirs.json`);
      dispatch(receiveFactoryDriveDirs(directories.data));
    } catch (err: unknown) {
      if (isAxiosError(err)) {
        dispatch(error.actions.setAndShowErrorDialog(
          `error fetching factory drives or dirs\n\n${err.message}`));
      } else {
        throw err;
      }
    }
  };
