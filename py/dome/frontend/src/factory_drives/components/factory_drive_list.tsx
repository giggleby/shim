// Copyright 2018 The Chromium OS Authors. All rights reserved.
// Use of this source code is governed by a BSD-style license that can be
// found in the LICENSE file.

import ArrowBackIcon from '@mui/icons-material/ArrowBack';
import BorderColorIcon from '@mui/icons-material/BorderColor';
import CloudUploadIcon from '@mui/icons-material/CloudUpload';
import UpdateIcon from '@mui/icons-material/Update';
import Button from '@mui/material/Button';
import grey from '@mui/material/colors/grey';
import Dialog from '@mui/material/Dialog';
import DialogActions from '@mui/material/DialogActions';
import DialogContent from '@mui/material/DialogContent';
import DialogTitle from '@mui/material/DialogTitle';
import IconButton from '@mui/material/IconButton';
import List from '@mui/material/List';
import ListItem from '@mui/material/ListItem';
import ListItemIcon from '@mui/material/ListItemIcon';
import ListSubheader from '@mui/material/ListSubheader';
import {Theme} from '@mui/material/styles';
import Tooltip from '@mui/material/Tooltip';
import Typography from '@mui/material/Typography';
import {
  createStyles,
  withStyles,
  WithStyles,
} from '@mui/styles';
import classNames from 'classnames';
import React from 'react';
import {connect} from 'react-redux';

import formDialog from '@app/form_dialog';
import {RootState} from '@app/types';

import {thinScrollBarX} from '@common/styles';
import {DispatchProps} from '@common/types';

import {fetchFactoryDrives, startUpdateComponentVersion} from '../actions';
import {
  RENAME_DIRECTORY_FORM,
  RENAME_FACTORY_DRIVE_FORM,
  UPDATE_FACTORY_DRIVE_FORM,
} from '../constants';
import {getFactoryDriveDirs, getFactoryDrives} from '../selector';
import {FactoryDrive} from '../types';

import RenameDirectoryForm from './rename_directory_form';
import RenameFactoryDriveForm from './rename_factory_drive_form';

const styles = (theme: Theme) => createStyles({
  directoryTable: {
    display: 'grid',
    gridTemplateColumns: '1fr auto',
    width: '100%',
  },
  componentTable: {
    display: 'grid',
    gridTemplateColumns: '1fr auto auto auto',
    width: '100%',
  },
  revisionTable: {
    display: 'grid',
    gridTemplateColumns: '32px 1fr 2fr auto',
    width: '100%',
  },
  cell: {
    padding: theme.spacing(1),
    display: 'flex',
    alignItems: 'center',
    borderBottom: `1px solid ${grey[300]}`,
    fontSize: theme.typography.pxToRem(13),
    ...thinScrollBarX,
  },
  ellipsis: {
    overflow: 'hidden',
    whiteSpace: 'nowrap',
    textOverflow: 'ellipsis',
  },
  actionColumn: {
    justifyContent: 'center',
    gridColumn: 'span 3',
  },
  directoryLabel: {
    justifyContent: 'left',
    textTransform: 'none',
    fontWeight: theme.typography.fontWeightRegular,
  },
  padLeft: {
    paddingLeft: 24,
  },
  revisionActionColumn: {
    justifyContent: 'center',
  },
  bold: {
    fontWeight: 600,
  },
});

interface FactoryDriveListState {
  openedComponentId: number | null;
}

interface FactoryDriveListOwnProps {
  currentDirId: number | null;
  dirClicked: (id: number | null) => any;
}

type FactoryDriveListProps =
  FactoryDriveListOwnProps &
  WithStyles<typeof styles> &
  ReturnType<typeof mapStateToProps> &
  DispatchProps<typeof mapDispatchToProps>;

class FactoryDriveList extends
  React.Component<FactoryDriveListProps, FactoryDriveListState> {

  state = {openedComponentId: null};

  handleClickDir = (dirId: number | null) => {
    this.props.dirClicked(dirId);
  }

  handleClickBack = (dirId: number | null) => {
    if (dirId == null) {
      return;
    }
    this.handleClickDir(this.props.factoryDriveDirs[dirId].parentId);
  }

  handleClickVersion = (compId: number) => {
    this.setState({openedComponentId: compId});
  }

  handleCloseClickVersion = () => {
    this.setState({openedComponentId: null});
  }

  handleRenameFactoryDrive = (compId: number) => {
    this.props.renameFactoryDrive(
      compId,
      this.props.factoryDrives[compId].name,
    );
  }

  handleRenameDirectory = (dirId: number) => {
    this.props.renameDirectory(dirId, this.props.factoryDriveDirs[dirId].name);
  }

  componentDidMount() {
    this.props.fetchFactoryDrives();
  }

  render() {
    const {currentDirId, classes, factoryDrives, factoryDriveDirs} = this.props;
    const {openedComponentId} = this.state;
    const openedComponent =
      openedComponentId == null ? null : factoryDrives[openedComponentId];

    const getPath = (dirId: number | null): string => {
      if (dirId == null) {
        return '/';
      }
      const dir = factoryDriveDirs[dirId];
      return `${getPath(dir.parentId)}${dir.name}/`;
    };
    const currentPath = getPath(currentDirId);

    const directoryTable = (
      <div className={classes.directoryTable}>
        <RenameDirectoryForm />
        <div className={classNames(classes.cell, classes.padLeft)}>
          <Typography variant="caption">name</Typography>
        </div>
        <div className={classNames(classes.cell)}>
          <Typography variant="caption">actions</Typography>
        </div>
        {factoryDriveDirs
          .filter((dir) => dir.parentId === currentDirId)
          .map((factoryDriveDir) => (
            <React.Fragment key={factoryDriveDir.id}>
              <div className={classNames(classes.cell, classes.padLeft)}>
                <Button
                  classes={{root: classes.directoryLabel}}
                  fullWidth
                  onClick={() => this.handleClickDir(factoryDriveDir.id)}
                >
                  {factoryDriveDir.name}
                </Button>
              </div>
              <div className={classes.cell}>
                <Tooltip title="Rename">
                  <IconButton
                    onClick={
                      () => this.handleRenameDirectory(factoryDriveDir.id)
                    }
                  >
                    <BorderColorIcon />
                  </IconButton>
                </Tooltip>
              </div>
            </React.Fragment>
          ))}
      </div>);

    const componentTable = (
      <div className={classes.componentTable}>
        <RenameFactoryDriveForm />
        <div className={classNames(classes.cell, classes.padLeft)}>
          <Typography variant="caption">name</Typography>
        </div>
        <div className={classNames(classes.cell, classes.actionColumn)}>
          <Typography variant="caption">actions</Typography>
        </div>
        {factoryDrives
          .filter((factoryDrive) => factoryDrive.dirId === currentDirId)
          .map((factoryDrive) => (
            <React.Fragment key={factoryDrive.id}>
              <div className={classNames(classes.cell, classes.padLeft)}>
                {factoryDrive.name}
              </div>
              <div className={classes.cell}>
                <Tooltip title="Rename">
                  <IconButton
                    onClick={
                      () => this.handleRenameFactoryDrive(factoryDrive.id)
                    }
                  >
                    <BorderColorIcon />
                  </IconButton>
                </Tooltip>
              </div>
              <div className={classes.cell}>
                <Tooltip title="Versions">
                  <IconButton
                    onClick={() => this.handleClickVersion(factoryDrive.id)}
                  >
                    <UpdateIcon />
                  </IconButton>
                </Tooltip>
              </div>
              <div className={classes.cell}>
                <Tooltip title="Update" className={classes.cell}>
                  <IconButton
                    onClick={() => this.props.updateComponent(
                      factoryDrive.id,
                      factoryDrive.dirId,
                      factoryDrive.name,
                      false,
                    )}
                  >
                    <CloudUploadIcon />
                  </IconButton>
                </Tooltip>
              </div>
            </React.Fragment>
          ))}
      </div>);

    // TODO(pihsun): Move revision dialog into another component.
    const revisionTable = (component: FactoryDrive) => (
      <div className={classes.revisionTable}>
        <div className={classes.cell}>
          <Typography variant="caption">ID</Typography>
        </div>
        <div className={classes.cell}>
          <Typography variant="caption">name</Typography>
        </div>
        <div className={classes.cell}>
          <Typography variant="caption">hash</Typography>
        </div>
        <div className={classNames(classes.cell, classes.revisionActionColumn)}>
          <Typography variant="caption">actions</Typography>
        </div>
        {component.revisions.map((filePath, versionId) => {
          // Generate file name and hash from file path form:
          // {filePath}/{fileName}.{md5hash}
          const baseName = filePath.split('/').pop();
          const parts = baseName ? baseName.split('.') : undefined;
          const hash = parts ? parts.pop() : undefined;
          const fileName = parts ? parts.join('.') : undefined;
          const isUsing = component.usingVer === versionId;
          const rowClass = classNames(classes.cell, isUsing && classes.bold);
          return (
            <React.Fragment key={versionId}>
              <div className={rowClass}>{versionId}</div>
              <div className={rowClass}>{fileName}</div>
              <div className={classNames(rowClass, classes.ellipsis)}>
                {hash}
              </div>
              <div className={classes.cell}>
                <Button
                  onClick={() => this.props.updateComponentVersion(
                            component.id, component.name, versionId)}
                  color="primary"
                  fullWidth
                >
                  {isUsing ? 'Using' : 'Use'}
                </Button>
              </div>
            </React.Fragment>
          );
        })}
      </div>);

    return (
      <List>
        <ListItem disableGutters dense>
          <ListItemIcon>
            <IconButton
              onClick={() => this.handleClickBack(currentDirId)}
              disabled={currentDirId == null}
            >
              <ArrowBackIcon />
            </IconButton>
          </ListItemIcon>
          <Typography variant="body1">
            Current directory: {currentPath}
          </Typography>
        </ListItem>
        <ListSubheader>Directories</ListSubheader>
        <ListItem>{directoryTable}</ListItem>
        <ListSubheader>Files</ListSubheader>
        <ListItem>{componentTable}</ListItem>

        <Dialog
          open={openedComponentId != null}
          onClose={this.handleCloseClickVersion}
        >
          {openedComponent != null &&
            <>
              <DialogTitle id="scroll-dialog-title">
                Revisions of file {openedComponent.name}
              </DialogTitle>
              <DialogContent>
                {revisionTable(openedComponent)}
              </DialogContent>
              <DialogActions>
                <Button
                  onClick={this.handleCloseClickVersion}
                  color="primary"
                >
                  Close
                </Button>
              </DialogActions>
            </>
          }
        </Dialog>
      </List>
    );
  }
}

const mapStateToProps = (state: RootState) => ({
  factoryDrives: getFactoryDrives(state),
  factoryDriveDirs: getFactoryDriveDirs(state),
});

const mapDispatchToProps = {
  fetchFactoryDrives,
  updateComponent:
    (id: number, dirId: number | null, name: string, multiple: boolean) =>
      formDialog.actions.openForm(
        UPDATE_FACTORY_DRIVE_FORM, {id, dirId, name, multiple}),
  updateComponentVersion: (id: number, name: string, usingVer: number) =>
    startUpdateComponentVersion({id, name, usingVer}),
  renameFactoryDrive: (id: number, name: string) =>
    formDialog.actions.openForm(RENAME_FACTORY_DRIVE_FORM, {id, name}),
  renameDirectory: (id: number, name: string) =>
    formDialog.actions.openForm(RENAME_DIRECTORY_FORM, {id, name}),
};

export default connect(mapStateToProps, mapDispatchToProps)(
  withStyles(styles)(FactoryDriveList));
