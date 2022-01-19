// Copyright 2018 The Chromium OS Authors. All rights reserved.
// Use of this source code is governed by a BSD-style license that can be
// found in the LICENSE file.

import Card from '@mui/material/Card';
import CardContent from '@mui/material/CardContent';
import IconButton from '@mui/material/IconButton';
import {
  createStyles,
  withStyles,
  WithStyles,
} from '@mui/styles';
import {Theme} from '@mui/material/styles';
import Tooltip from '@mui/material/Tooltip';
import Typography from '@mui/material/Typography';
import CreateNewFolderIcon from '@mui/icons-material/CreateNewFolder';
import NoteAddIcon from '@mui/icons-material/NoteAdd';
import React from 'react';
import {connect} from 'react-redux';

import formDialog from '@app/form_dialog';
import {DispatchProps} from '@common/types';

import {CREATE_DIRECTORY_FORM, UPDATE_PARAMETER_FORM} from '../constants';

import CreateDirectoryForm from './create_directory_form';
import ParameterList from './parameter_list';
import UpdateParameterDialog from './update_parameter_dialog';

const styles = (theme: Theme) => createStyles({
  header: {
    display: 'flex',
    alignItems: 'center',
  },
  headerButtonGroup: {
    display: 'flex',
    justifyContent: 'flex-end',
    width: '100%',
  },
});

interface ParameterState {
  currentDirId: number | null;
}

type ParameterAppProps =
  WithStyles<typeof styles> &
  DispatchProps<typeof mapDispatchToProps>;

class ParameterApp extends React.Component<ParameterAppProps, ParameterState> {

  state = {currentDirId: null};

  setCurrentDirId = (id: number | null) => {
    this.setState({currentDirId: id});
  }

  render() {
    const {currentDirId} = this.state;
    const {classes} = this.props;
    return (
      <>
        <UpdateParameterDialog />
        <CreateDirectoryForm dirId={currentDirId}/>
        <Card>
          <CardContent className={classes.header}>
            <Typography variant="h5">Parameter</Typography>
            <div className={classes.headerButtonGroup}>
              <Tooltip title="Create Files">
                <IconButton
                  color="primary"
                  onClick={() => this.props.updateComponent(
                    this.state.currentDirId, 'unused_name', true)}
                >
                  <NoteAddIcon />
                </IconButton>
              </Tooltip>
              <Tooltip title="Add directory">
                <IconButton
                  color="primary"
                  onClick={this.props.createDirectory}
                >
                  <CreateNewFolderIcon />
                </IconButton>
              </Tooltip>
            </div>
          </CardContent>
          <CardContent>
            <ParameterList
              currentDirId={currentDirId}
              dirClicked={this.setCurrentDirId}
            />
          </CardContent>
        </Card>
      </>
    );
  }

}

const mapDispatchToProps = {
  updateComponent:
      (dirId: number | null, name: string, multiple: boolean) =>
          (formDialog.actions.openForm(
              UPDATE_PARAMETER_FORM, {id: null, dirId, name, multiple})),
  createDirectory: () => formDialog.actions.openForm(CREATE_DIRECTORY_FORM),
};

export default connect(null, mapDispatchToProps)(
  withStyles(styles)(ParameterApp));
