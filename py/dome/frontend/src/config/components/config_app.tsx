// Copyright 2017 The ChromiumOS Authors
// Use of this source code is governed by a BSD-style license that can be
// found in the LICENSE file.

import Button from '@mui/material/Button';
import Card from '@mui/material/Card';
import CardActions from '@mui/material/CardActions';
import CardContent from '@mui/material/CardContent';
import CardHeader from '@mui/material/CardHeader';
import FormControlLabel from '@mui/material/FormControlLabel';
import Switch from '@mui/material/Switch';
import React from 'react';
import {connect} from 'react-redux';

import auth from '@app/auth';
import {RootState} from '@app/types';

import {DispatchProps} from '@common/types';

import {
  disableMcast,
  disableTftp,
  disableVersionCheck,
  enableMcast,
  enableTftp,
  enableVersionCheck,
  fetchConfig,
} from '../actions';
import {
  isConfigUpdating,
  isMcastEnabled,
  isTftpEnabled,
  isVersionCheckEnabled,
} from '../selectors';

type ConfigAppProps =
  ReturnType<typeof mapStateToProps> & DispatchProps<typeof mapDispatchToProps>;

class ConfigApp extends React.Component<ConfigAppProps> {
  componentDidMount() {
    this.props.fetchConfig();
  }

  render() {
    const {
      isMcastEnabled,
      isTftpEnabled,
      isVersionCheckEnabled,
      isConfigUpdating,
      disableMcast,
      disableTftp,
      disableVersionCheck,
      enableMcast,
      enableTftp,
      enableVersionCheck,
      logout,
    } = this.props;

    return (
      <Card>
        <CardHeader title="Config" />
        <CardContent>
          <FormControlLabel
            control={
              <Switch
                color="primary"
                checked={isTftpEnabled}
                onChange={isTftpEnabled ? disableTftp : enableTftp}
                disabled={isConfigUpdating}
              />
            }
            label="TFTP server"
          />
          <FormControlLabel
            control={
              <Switch
                color="primary"
                checked={isMcastEnabled}
                onChange={isMcastEnabled ? disableMcast : enableMcast}
                disabled={isConfigUpdating}
              />
            }
            label="Multicast netboot"
          />
          <FormControlLabel
            control={
              <Switch
                color="primary"
                checked={isVersionCheckEnabled}
                onChange={isVersionCheckEnabled ? disableVersionCheck :
                          enableVersionCheck}
                disabled={isConfigUpdating}
              />
            }
            label="DOME latest version auto check"
          />
        </CardContent>
        <CardActions>
          <Button color="primary" size="small" onClick={logout}>
            logout
          </Button>
        </CardActions>
      </Card>
    );
  }
}

const mapStateToProps = (state: RootState) => ({
  isTftpEnabled: isTftpEnabled(state),
  isMcastEnabled: isMcastEnabled(state),
  isVersionCheckEnabled: isVersionCheckEnabled(state),
  isConfigUpdating: isConfigUpdating(state),
});

const mapDispatchToProps = {
  disableMcast,
  disableTftp,
  disableVersionCheck,
  enableMcast,
  enableTftp,
  enableVersionCheck,
  fetchConfig,
  logout: auth.actions.logout,
};

export default connect(mapStateToProps, mapDispatchToProps)(ConfigApp);
