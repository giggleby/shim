// Copyright 2016 The Chromium OS Authors. All rights reserved.
// Use of this source code is governed by a BSD-style license that can be
// found in the LICENSE file.

import Card from '@mui/material/Card';
import CardContent from '@mui/material/CardContent';
import CardHeader from '@mui/material/CardHeader';
import Divider from '@mui/material/Divider';
import FormControlLabel from '@mui/material/FormControlLabel';
import List from '@mui/material/List';
import ListItem from '@mui/material/ListItem';
import ListSubheader from '@mui/material/ListSubheader';
import Switch from '@mui/material/Switch';
import React from 'react';
import {connect} from 'react-redux';

import formDialog from '@app/form_dialog';
import project from '@app/project';
import ServiceList from '@app/service/components/service_list';
import {RootState} from '@app/types';

import {DispatchProps} from '@common/types';

import {disableUmpire, enableUmpireWithSettings, fetchPorts, removeProjectPort} from '../actions';
import {ENABLE_UMPIRE_FORM} from '../constants';
import {getPorts} from '../selectors';

import EnableUmpireForm from './enable_umpire_form';

type DashboardAppProps =
  ReturnType<typeof mapStateToProps> & DispatchProps<typeof mapDispatchToProps>;

class DashboardApp extends React.Component<DashboardAppProps> {
  handleToggle = () => {
    const {
      project: {umpireEnabled, name},
      ports,
      disableUmpire,
      openEnableUmpireForm,
      fetchPorts,
      removeProjectPort,
    } = this.props;
    if (umpireEnabled) {
      disableUmpire(name);
      removeProjectPort(ports, name);
    } else {
      fetchPorts();
      openEnableUmpireForm();
    }
  }

  componentDidMount() {
    this.props.fetchPorts();
  }

  render() {
    const {
      project,
      closeEnableUmpireForm,
      enableUmpireWithSettings,
    } = this.props;

    return (
      <>
        {/* TODO(littlecvr): add <ProductionLineInfoPanel /> */}

        <Card>
          <CardHeader title="Dashboard" />
          <CardContent>
            <FormControlLabel
              control={
                <Switch
                  color="primary"
                  checked={project.umpireEnabled}
                  disableRipple
                />
              }
              label="Enable Umpire"
              onChange={this.handleToggle}
            />
            <List>
              {project.umpireEnabled && project.umpireReady &&
                <>
                  <ListSubheader>Info</ListSubheader>
                  <Divider />
                  <ListItem>
                    port: {project.umpirePort}
                  </ListItem>
                  <ListSubheader>Services</ListSubheader>
                  <ServiceList />
                </>}
            </List>
          </CardContent>
        </Card>

        {/* TODO(littlecvr): add <SystemInfoPanel /> */}

        <EnableUmpireForm
          project={project}
          onCancel={closeEnableUmpireForm}
          onSubmit={(umpireSettings) => {
            closeEnableUmpireForm();
            enableUmpireWithSettings(project.name, umpireSettings);
          }}
        />
      </>
    );
  }
}

const mapStateToProps = (state: RootState) => ({
  project: project.selectors.getCurrentProjectObject(state)!,
  ports: getPorts(state),
});

const mapDispatchToProps = {
  fetchPorts,
  removeProjectPort,
  disableUmpire,
  enableUmpireWithSettings,
  openEnableUmpireForm: () => formDialog.actions.openForm(ENABLE_UMPIRE_FORM),
  closeEnableUmpireForm: () => formDialog.actions.closeForm(ENABLE_UMPIRE_FORM),
};

export default connect(mapStateToProps, mapDispatchToProps)(DashboardApp);
