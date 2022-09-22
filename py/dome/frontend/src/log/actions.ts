// Copyright 2019 The ChromiumOS Authors
// Use of this source code is governed by a BSD-style license that can be
// found in the LICENSE file.

import {createAction} from 'typesafe-actions';

import error from '@app/error';
import {Dispatch, RootState} from '@app/types';
import {authorizedAxios, isAxiosError} from '@common/utils';

import {
  getOverallDownloadStateFromStateMap,
  getPiles,
} from './selectors';
import {ComponentState} from './types';

export const removeLogPile =
  createAction('REMOVE_DOWNLOAD_PILE', (resolve) =>
    (key: string) => resolve({key}));

export const expandLogPile =
  createAction('EXPAND_DOWNLOAD_COMPONENT', (resolve) =>
    (key: string) => resolve({key}));

export const collapseLogPile =
  createAction('COLLAPSE_DOWNLOAD_COMPONENT', (resolve) =>
    (key: string) => resolve({key}));

export const removeDownloadFile =
  createAction('REMOVE_DOWNLOAD_FILE', (resolve) =>
    (key: string, file: string) => resolve({key, file}));

export const removeDownloadFiles =
  createAction('REMOVE_DOWNLOAD_FILES', (resolve) =>
    (key: string) => resolve({key}));

const setDefaultDownloadDate =
  createAction('SET_DEFAULT_DOWNLOAD_DATE', (resolve) =>
    (projectName: string, date: string) =>
      resolve({projectName, date}));

const addLogPile =
  createAction('ADD_DOWNLOAD_PILE', (resolve) =>
    (key: string, title: string, projectName: string, actionType: string) =>
      resolve({key, title, projectName, actionType}));

const setCompressState =
  createAction('SET_COMPRESS_STATE', (resolve) =>
    (key: string, newState: ComponentState) => resolve({key, newState}));

const setCleanupState =
  createAction('SET_CLEANUP_STATE', (resolve) =>
    (key: string, newState: ComponentState) => resolve({key, newState}));

const addDownloadFile =
  createAction('ADD_DOWNLOAD_FILE', (resolve) =>
    (key: string, file: string) => resolve({key, file}));

const setDownloadState =
  createAction('SET_DOWNLOAD_STATE', (resolve) =>
    (key: string, file: string, newState: ComponentState) =>
      resolve({key, file, newState}));

const setTempDir =
  createAction('SET_TEMP_DIR', (resolve) =>
    (key: string, tempDir: string) => resolve({key, tempDir}));

const setReportMessages =
  createAction('SET_REPORT_MESSAGES', (resolve) =>
    (key: string, messages: string[]) => resolve({key, messages}));

const setCleanupReportMessages =
  createAction('SET_CLEANUP_REPORT_MESSAGES', (resolve) =>
    (key: string, messages: string[]) => resolve({key, messages}));

export const basicActions = {
  setDefaultDownloadDate,
  expandLogPile,
  collapseLogPile,
  addLogPile,
  removeLogPile,
  setCompressState,
  setCleanupState,
  addDownloadFile,
  removeDownloadFile,
  removeDownloadFiles,
  setDownloadState,
  setTempDir,
  setReportMessages,
  setCleanupReportMessages,
};

export const exportLog = (projectName: string,
                          logType: string,
                          archiveSize: number,
                          archiveSizeUnit: string,
                          startDate: string,
                          endDate: string,
                          actionType: string) =>
  async (dispatch: Dispatch) => {
    let response;
    const pileKey = `${logType}-${startDate}-${endDate}-${Math.random()}`;
    const dates = (startDate === endDate) ?
        startDate : `${startDate} ~ ${endDate}`;
    const title = (logType === 'csv') ? logType : `${logType} ${dates}`;
    switch (actionType) {
      case 'download':
        dispatch(addLogPile(pileKey, title, projectName, actionType));
        try {
          dispatch(setCompressState(pileKey, 'PROCESSING'));
          response = await authorizedAxios().post(
              `projects/${projectName}/log/compress/`,
              {logType, archiveSize, archiveSizeUnit, startDate, endDate});
          dispatch(setCompressState(pileKey, 'SUCCEEDED'));
        } catch (unknownError: unknown) {
          if (isAxiosError(unknownError)) {
            dispatch(setCompressState(pileKey, 'FAILED'));
            const message = unknownError.response?.data.detail;
            dispatch(error.actions.setAndShowErrorDialog(
                `error compressing log\n\n${message}`));
            return;
          } else {
            throw unknownError;
          }
        }
        const {
          logPaths,
          tmpDir,
          messages,
        } = response.data;
        dispatch(setReportMessages(pileKey, messages));
        dispatch(setTempDir(pileKey, tmpDir));
        dispatch(downloadLogs(projectName, tmpDir, logPaths, pileKey));
        dispatch(setDefaultDownloadDate(projectName, endDate));
        break;
      case 'cleanup':
        dispatch(addLogPile(pileKey, title, projectName, actionType));
        try {
          dispatch(setCleanupState(pileKey, 'PROCESSING'));
          response = await authorizedAxios().delete(
              `projects/${projectName}/log/delete_files/`,
              {data: {logType, startDate, endDate}});
          dispatch(setCleanupState(pileKey, 'SUCCEEDED'));
        } catch (unknownError: unknown) {
          if (isAxiosError(unknownError)) {
            dispatch(setCleanupState(pileKey, 'FAILED'));
            const message = unknownError.response?.data.detail;
            dispatch(error.actions.setAndShowErrorDialog(
                `error compressing log\n\n${message}`));
            return;
          } else {
            throw unknownError;
          }
        }
        dispatch(setCleanupReportMessages(pileKey, response.data.messages));
        break;
      default:
        return;
    }
  };

export const downloadLogs = (projectName: string,
                             tempDir: string,
                             logPaths: string[],
                             pileKey: string) =>
  async (dispatch: Dispatch, getState: () => RootState) => {
    if (!logPaths.length) {
      deleteDirectory(projectName, tempDir);
      return;
    }
    const downloads = logPaths.map(
      async (logPath: string) =>
        dispatch(downloadLog(projectName, tempDir, logPath, pileKey)));
    await Promise.all(downloads);
    if (getOverallDownloadState(getState(), pileKey) === 'SUCCEEDED') {
      deleteDirectory(projectName, tempDir);
    }
  };

export const downloadLog = (projectName: string,
                            tempDir: string,
                            logFile: string,
                            pileKey: string) =>
  async (dispatch: Dispatch) => {
    dispatch(addDownloadFile(pileKey, logFile));
    try {
      const response = await authorizedAxios().get(
          `projects/${projectName}/log/download/`, {
        responseType: 'blob',
        params: {
          log_file: logFile,
          temp_dir: tempDir,
        },
      });
      const link = document.createElement('a');
      link.href = window.URL.createObjectURL(response.data);
      link.download = `${projectName}-${logFile}`;
      link.click();
      window.URL.revokeObjectURL(link.href);
      dispatch(setDownloadState(pileKey, logFile, 'SUCCEEDED'));
    } catch (unknownError: unknown) {
      dispatch(setDownloadState(pileKey, logFile, 'FAILED'));
    }
  };

export const deleteDirectory = async (projectName: string,
                                      tempDir: string) => {
  await authorizedAxios().delete(
    `projects/${projectName}/log/delete/`,
    {data: {tempDir}});
};

const getOverallDownloadState =
  (state: RootState, pileKey: string): ComponentState => {
    const downloadStateMap = getPiles(state)[pileKey].downloadStateMap;
    return getOverallDownloadStateFromStateMap(downloadStateMap);
  };
