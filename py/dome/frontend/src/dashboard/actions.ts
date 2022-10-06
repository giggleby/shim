// Copyright 2018 The ChromiumOS Authors
// Use of this source code is governed by a BSD-style license that can be
// found in the LICENSE file.

import {createAction} from 'typesafe-actions';

import project from '@app/project';
import {UmpireSetting} from '@app/project/types';
import {Dispatch} from '@app/types';
import {authorizedAxios} from '@common/utils';

import {PortResponse} from './types';

export const disableUmpire = (projectName: string) => (
  project.actions.updateProject(
    projectName,
    {umpireEnabled: false},
    `Disable Umpire for project "${projectName}"`)
);

export const enableUmpireWithSettings =
  (projectName: string, umpireSettings: Partial<UmpireSetting>) => (
    project.actions.updateProject(
      projectName,
      {umpireEnabled: true, ...umpireSettings},
      `Enable Umpire for project "${projectName}"`)
  );

const receivePorts = createAction('RECEIVE_PORTS', (resolve) =>
  (ports: PortResponse) => resolve({ports}));

const removePorts = createAction('REMOVE_PORTS', (resolve) =>
  (ports: PortResponse, projectName: string) => resolve({ports, projectName}));

export const basicActions = {
  receivePorts,
  removePorts,
};

export const fetchPorts = () => async (dispatch: Dispatch) => {
  const response = await authorizedAxios().get<PortResponse>('/project_ports');
  dispatch(receivePorts(response.data));
};

export const removeProjectPort = (ports: PortResponse, projectName: string) =>
  async (dispatch: Dispatch) => {
  dispatch(removePorts(ports, projectName));
};
