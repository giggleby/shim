// Copyright 2019 The ChromiumOS Authors
// Use of this source code is governed by a BSD-style license that can be
// found in the LICENSE file.

import Button from '@mui/material/Button';
import Card from '@mui/material/Card';
import CardActions from '@mui/material/CardActions';
import CardContent from '@mui/material/CardContent';
import Dialog from '@mui/material/Dialog';
import DialogActions from '@mui/material/DialogActions';
import DialogContent from '@mui/material/DialogContent';
import DialogTitle from '@mui/material/DialogTitle';
import Divider from '@mui/material/Divider';
import List from '@mui/material/List';
import ListItem from '@mui/material/ListItem';
import ListSubheader from '@mui/material/ListSubheader';
import MenuItem from '@mui/material/MenuItem';
import {Theme} from '@mui/material/styles';
import {
  createStyles,
  WithStyles,
  withStyles,
} from '@mui/styles';
import React from 'react';
import {connect} from 'react-redux';
import {
  FormErrors,
  formValueSelector,
  InjectedFormProps,
  reduxForm,
} from 'redux-form';

import {RootState} from '@app/types';
import ReduxFormTextField from '@common/components/redux_form_text_field';

import {getDefaultDownloadDate} from '../selectors';
import {LogFormData} from '../types';

import ReduxFormDateField from './redux_form_date_field';
import ReduxFormTabsField from './redux_form_tabs_field';

const units = ['MB', 'GB'];

const logTypes = [
  {name: 'log', value: 'log'},
  {name: 'report', value: 'report'},
  {name: 'csv (echo code inside)', value: 'csv'},
];

interface LogFormOwnProps {
  logType: string;
}

const styles = (theme: Theme) => createStyles({
  root: {
    marginBottom: theme.spacing(4),
  },
});

type LogFormProps =
  WithStyles<typeof styles> &
  LogFormOwnProps &
  ReturnType<typeof mapStateToProps>;

const validate = (values: LogFormData, props: LogFormProps) => {
  const errors: FormErrors<LogFormData> = {};
  const {
    archiveSize,
    startDate,
    endDate,
  } = values;

  if (startDate > endDate) {
    errors.startDate = 'start date must be before end date';
    errors.endDate = 'start date must be before end date';
  }

  if (!archiveSize) {
    errors.archiveSize = 'required';
  } else if (archiveSize <= 0) {
    errors.archiveSize = 'archive size must be larger than 0';
  }

  return errors;
};

class LogForm extends React.Component<
  LogFormProps
  & InjectedFormProps<LogFormData, LogFormProps>> {
  state = {
    open: false,
    actionType: '',
  };

  handleSelect = (
    event: any,
    value: string,
  ) => {
    this.setState({actionType: value});
  };

  handleClose = () => {
    this.setState({open: false});
  };

  render() {
    const {
      handleSubmit,
      logType,
      classes,
    } = this.props;
    const {actionType} = this.state;

    let actionTypeComponent = null;
    if (actionType === 'download') {
      actionTypeComponent =
        (
          <>
            <Divider />
            {(logType === 'csv') ||
              <List>
                <ListSubheader>Maximum Archive Size</ListSubheader>
                <ListItem>
                  <ReduxFormTextField
                    name="archiveSize"
                    label="size"
                    type="number"
                  />
                  <ReduxFormTextField
                    name="archiveUnit"
                    label="unit"
                    select
                  >
                    {units.map((option) => (
                      <MenuItem key={option} value={option}>
                        {option}
                      </MenuItem>
                    ))}
                  </ReduxFormTextField>
                </ListItem>
                <ListSubheader>Dates</ListSubheader>
                <ListItem>
                  <ReduxFormDateField
                    name="startDate"
                    label="start date"
                    ignoreTouch
                  />
                  <ReduxFormDateField
                    name="endDate"
                    label="end date"
                    ignoreTouch
                  />
                </ListItem>
                {/* <ListSubheader>Action on file</ListSubheader>
                <ListItem>
                  <ReduxFormTextField
                    name="actionType"
                    label="action"
                    select
                  >
                    {actions.map((option) => (
                      <MenuItem key={option.value} value={option.value}>
                        {option.name}
                      </MenuItem>
                    ))}
                  </ReduxFormTextField>
                </ListItem> */}
              </List>
            }
            <CardActions>
              <Button type="submit" color="primary">
                Download
              </Button>
            </CardActions>
          </>
        );
    } else if (actionType === 'cleanup') {
      actionTypeComponent =
        (
          <>
            <Divider />
            {(logType === 'csv') ||
              <List>
                <ListSubheader>Dates</ListSubheader>
                <ListItem>
                  <ReduxFormDateField
                    name="startDate"
                    label="start date"
                    ignoreTouch
                  />
                  <ReduxFormDateField
                    name="endDate"
                    label="end date"
                    ignoreTouch
                  />
                </ListItem>
              </List>
            }
            <CardActions>
              <Button
                type="button"
                color="primary"
                onClick={() => this.setState({open: true})}
              >
                {`Delete ${logType} file`}
              </Button>
            </CardActions>
            <Dialog open={this.state.open} onClose={this.handleClose}>
              <DialogTitle>Alert</DialogTitle>
              <DialogContent>
                All files will be deleted permanently. Do you want to continue?
              </DialogContent>
              <DialogActions>
                <Button
                  form="logForm"
                  type="submit"
                  color="primary"
                  onClick={() => this.setState({open: false})}
                >
                  OK
                </Button>
                <Button onClick={this.handleClose}>Cancel</Button>
              </DialogActions>
            </Dialog>
          </>
        );
    }

    return (
      <form id="logForm" onSubmit={handleSubmit}>
        <Card className={classes.root}>
          <CardContent>
            <ReduxFormTabsField
              name="logType"
              tab_types={logTypes}
            />
          </CardContent>
          <CardContent sx={{paddingTop: 0}}>
            <List>
              <ListItem>
                <ReduxFormTextField
                  name="actionType"
                  label="action type"
                  select
                  onChange={this.handleSelect}
                >
                  {['download', 'cleanup'].map((option) => (
                    <MenuItem key={option} value={option}>
                      {option}
                    </MenuItem>
                  ))}
                </ReduxFormTextField>
              </ListItem>
            </List>
            {actionTypeComponent}
          </CardContent>
        </Card>
      </form>
    );
  }
}

const selector = formValueSelector('logForm');

const mapStateToProps = (state: RootState) => ({
  logType: selector(state, 'logType'),
  initialValues: {
    logType: 'log',
    archiveSize: 200,
    archiveUnit: 'MB',
    startDate: getDefaultDownloadDate(state),
    endDate: getDefaultDownloadDate(state),
    actionType: '',
  },
});

export default withStyles(styles)(connect(mapStateToProps)(
  reduxForm<LogFormData, LogFormProps>({
    form: 'logForm',
    validate,
    enableReinitialize: true,
})(LogForm)));
