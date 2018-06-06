// Copyright 2018 The Chromium OS Authors. All rights reserved.
// Use of this source code is governed by a BSD-style license that can be
// found in the LICENSE file.

import {switchApp} from '../app/actions';
import {AppNames} from '../app/constants';
import {authorizedFetch} from '../common/utils';
import {runTask} from '../task/actions';

import actionTypes from './actionTypes';

// TODO(pihsun): Have a better way to handle task cancellation.
const buildOnCancel = (dispatch, getState) => {
  const projectsSnapshot =
      getState().getIn(['project', 'projects']).toList();
  return () => dispatch(receiveProjects(projectsSnapshot.toJS()));
};

export const createProject = (name) => async (dispatch) => {
  const description = `Create project "${name}"`;
  const {cancel} = await dispatch(
      runTask(description, 'POST', '/projects/', {name}));
  if (!cancel) {
    await dispatch(fetchProjects());
  }
};

export const updateProject = (name, settings = {}) =>
  async (dispatch, getState) => {
    const body = {name};
    [
      'umpireEnabled',
      'umpireAddExistingOne',
      'umpireHost',
      'umpirePort',
      'netbootBundle',
    ].forEach((key) => {
      if (key in settings) {
        body[key] = settings[key];
      }
    });

    // taking snapshot must be earlier than optimistic update
    const onCancel = buildOnCancel(dispatch, getState);

    // optimistic update
    dispatch({
      type: actionTypes.UPDATE_PROJECT,
      project: Object.assign({
        name,
        umpireReady: false,
      }, settings),
    });

    const description = `Update project "${name}"`;
    const {cancel, response} = await dispatch(
        runTask(description, 'PUT', `/projects/${name}/`, body));
    if (cancel) {
      onCancel();
      return;
    }
    const json = await response.json();
    // WORKAROUND: Umpire is not ready as soon as it should be,
    // wait for 1 second to prevent the request from failing.
    // TODO(b/65393817): remove the timeout after the issue has been solved.
    setTimeout(() => {
      dispatch({
        type: actionTypes.UPDATE_PROJECT,
        project: {
          name,
          umpireVersion: json['umpireVersion'],
          isUmpireRecent: json['isUmpireRecent'],
          umpireReady: json['umpireEnabled'],
        },
      });
    }, 1000);
  };

export const deleteProject = (name) => async (dispatch) => {
  const {cancel} = await dispatch(runTask(
      `Delete project "${name}"`, 'DELETE', `/projects/${name}/`, {}));
  if (!cancel) {
    await dispatch(fetchProjects());
  }
};

const receiveProjects = (projects) => ({
  type: actionTypes.RECEIVE_PROJECTS,
  projects,
});

// TODO(littlecvr): similar to fetchBundles, refactor code if possible
export const fetchProjects = () => async (dispatch) => {
  const response = await authorizedFetch('/projects.json', {});
  const json = await response.json();
  dispatch(receiveProjects(json));
};

export const switchProject = (nextProject) => (dispatch, getState) => {
  dispatch({
    type: actionTypes.SWITCH_PROJECT,
    prevProject: getState().getIn(['project', 'currentProject']),
    nextProject,
  });
  // switch to dashboard after switching project by default
  dispatch(switchApp(AppNames.DASHBOARD_APP));
};
