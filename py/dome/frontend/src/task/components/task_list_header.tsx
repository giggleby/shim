// Copyright 2016 The ChromiumOS Authors
// Use of this source code is governed by a BSD-style license that can be
// found in the LICENSE file.

import DismissIcon from '@mui/icons-material/CheckCircle';
import DeleteIcon from '@mui/icons-material/Delete';
import CollapseIcon from '@mui/icons-material/ExpandLess';
import ExpandIcon from '@mui/icons-material/ExpandMore';
import IconButton from '@mui/material/IconButton';
import {Theme} from '@mui/material/styles';
import Tooltip from '@mui/material/Tooltip';
import Typography from '@mui/material/Typography';
import {
  createStyles,
  withStyles,
  WithStyles,
} from '@mui/styles';
import React from 'react';

import {isCancellable, isRunning} from '../constants';
import {Task, TaskState} from '../types';

import {styles as taskComponentStyles} from './task_component';

const styles = (theme: Theme) => createStyles({
  ...taskComponentStyles(theme),
});

interface TaskListHeaderProps extends WithStyles<typeof styles> {
  tasks: Task[];
  cancelAllWaitingTasks: () => void;
  dismissAllSucceededTasks: () => void;
  collapsed: boolean;
  setCollapsed: (collapsed: boolean) => void;
}

const TaskListHeader: React.SFC<TaskListHeaderProps> = ({
  tasks,
  cancelAllWaitingTasks,
  dismissAllSucceededTasks,
  collapsed,
  setCollapsed,
  classes,
}) => {
  const counts = tasks.reduce((groups, {state}) => {
    groups[state] = (groups[state] || 0) + 1;
    return groups;
  }, {} as {[state in TaskState]?: number});
  const running = tasks.filter(({state}) => isRunning(state)).length;
  const hasCancellableTask = tasks.some(({state}) => isCancellable(state));

  const taskSummary = `${counts.WAITING || 0} waiting, ` +
    `${running} running, ` +
    `${counts.SUCCEEDED || 0} succeeded, ` +
    `${counts.FAILED || 0} failed`;

  return (
    <>
      <div className={classes.description}>
        <Typography variant="body1">Tasks</Typography>
        <Typography variant="caption" color="textSecondary">
          {taskSummary}
        </Typography>
      </div>
      {collapsed ? (
        <>
          {/* two padding blank icons */}
          <div />
          <div />
          <IconButton onClick={() => setCollapsed(false)}>
            <ExpandIcon />
          </IconButton>
        </>
      ) : (
        <>
          <Tooltip title="cancel all waiting tasks">
            <div>
              {/* We need an extra div so tooltip works when button is disabled.
                */}
              <IconButton
                onClick={cancelAllWaitingTasks}
                disabled={!hasCancellableTask}
              >
                <DeleteIcon />
              </IconButton>
            </div>
          </Tooltip>
          <Tooltip title="dismiss all finished tasks">
            <IconButton onClick={dismissAllSucceededTasks}>
              <DismissIcon
                color="action"
                classes={{
                  colorAction: classes.colorAction,
                }}
              />
            </IconButton>
          </Tooltip>
          <IconButton onClick={() => setCollapsed(true)}>
            <CollapseIcon />
          </IconButton>
        </>
      )}
    </>
  );
};

export default withStyles(styles)(TaskListHeader);
