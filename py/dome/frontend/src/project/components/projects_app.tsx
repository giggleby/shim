// Copyright 2016 The ChromiumOS Authors
// Use of this source code is governed by a BSD-style license that can be
// found in the LICENSE file.

import DeleteIcon from '@mui/icons-material/Delete';
import Button from '@mui/material/Button';
import Card from '@mui/material/Card';
import CardContent from '@mui/material/CardContent';
import CardHeader from '@mui/material/CardHeader';
import Dialog from '@mui/material/Dialog';
import DialogActions from '@mui/material/DialogActions';
import DialogContent from '@mui/material/DialogContent';
import DialogTitle from '@mui/material/DialogTitle';
import Divider from '@mui/material/Divider';
import IconButton from '@mui/material/IconButton';
import List from '@mui/material/List';
import ListItem from '@mui/material/ListItem';
import ListItemSecondaryAction from '@mui/material/ListItemSecondaryAction';
import ListItemText from '@mui/material/ListItemText';
import {Theme} from '@mui/material/styles';
import Tooltip from '@mui/material/Tooltip';
import Typography from '@mui/material/Typography';
import {
  createStyles,
  withStyles,
  WithStyles,
} from '@mui/styles';
import React from 'react';
import {connect} from 'react-redux';
import {reset} from 'redux-form';

import {RootState} from '@app/types';

import {DispatchProps} from '@common/types';

import {
  createProject,
  deleteProject,
  fetchProjects,
  switchProject,
} from '../actions';
import {CREATE_PROJECT_FORM} from '../constants';
import {getProjects} from '../selectors';

import CreateProjectForm, {CreateProjectFormData} from './create_project_form';

const styles = (theme: Theme) => createStyles({
  center: {
    textAlign: 'center',
    justifyContent: 'center',
  },
  title: {
    textAlign: 'center',
    fontSize: theme.typography.h4.fontSize,
    fontWeight: theme.typography.fontWeightMedium,
  },
});

type ProjectAppProps =
  WithStyles<typeof styles> &
  ReturnType<typeof mapStateToProps> &
  DispatchProps<typeof mapDispatchToProps>;

interface DialogStates {
  open: boolean;
  name: string;
}
class ProjectsApp extends React.Component<ProjectAppProps, DialogStates> {
  state: DialogStates = {
    open: false,
    name: '',
  };

  handleSubmit = ({name}: CreateProjectFormData) => {
    this.props.createProject(name);
    this.props.resetForm();
  }

  handleClose = () => {
    this.setState({open: false});
  };

  componentDidMount() {
    this.props.fetchProjects();
  }

  render() {
    const {classes, projects, switchProject, deleteProject} = this.props;
    const projectNames = Object.keys(projects).sort();
    return (
      <>
      <Card>
        {/* TODO(littlecvr): make a logo! */}
        <CardHeader
          title="Project list"
          titleTypographyProps={{
            className: classes.title,
          }}
        />
        <CardContent>
          <Divider />
          <List>
            {projectNames.length === 0 ? (
              <ListItem className={classes.center}>
                <Typography variant="body1">
                  no projects, create or add an existing one
                </Typography>
              </ListItem>
            ) : (
              projectNames.map((name) => (
                <ListItem
                  key={name}
                  button
                  onClick={() => switchProject(name)}
                >
                  <ListItemText primary={name} />
                  <ListItemSecondaryAction>
                    <Tooltip title="delete this project">
                      <IconButton
                        color="inherit"
                        onClick={() => {
                          this.setState({open: true, name});
                        }}
                      >
                        <DeleteIcon />
                      </IconButton>
                    </Tooltip>
                  </ListItemSecondaryAction>
                </ListItem>
              ))
            )}
          </List>
          <Divider />
        </CardContent>

        <div className={classes.center}>OR</div>

        <CardContent>
          <CreateProjectForm
            projectNames={projectNames}
            onSubmit={this.handleSubmit}
          />
        </CardContent>
      </Card>

      <Dialog open={this.state.open} onClose={this.handleClose}>
        <DialogTitle>Alert</DialogTitle>
        <DialogContent>
        All files (including images, toolkit, uploaded logs) will be deleted.
        Do you want to continue?
        </DialogContent>
        <DialogActions>
          <Button
            color="primary"
            onClick={() => {
              deleteProject(this.state.name);
              this.setState({open: false});
            }}
          >
            OK
          </Button>
          <Button onClick={this.handleClose}>Cancel</Button>
        </DialogActions>
      </Dialog>
    </>
    );
  }
}

const mapStateToProps = (state: RootState) => ({
  projects: getProjects(state),
});

const mapDispatchToProps = {
  createProject,
  deleteProject,
  fetchProjects,
  switchProject,
  resetForm: () => reset(CREATE_PROJECT_FORM),
};

export default connect(mapStateToProps, mapDispatchToProps)(
  withStyles(styles)(ProjectsApp));
