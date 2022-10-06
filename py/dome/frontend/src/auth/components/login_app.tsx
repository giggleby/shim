// Copyright 2017 The ChromiumOS Authors
// Use of this source code is governed by a BSD-style license that can be
// found in the LICENSE file.

import CircularProgress from '@mui/material/CircularProgress';
import Modal from '@mui/material/Modal';
import {Theme} from '@mui/material/styles';
import {
  createStyles,
  withStyles,
  WithStyles,
} from '@mui/styles';
import React from 'react';
import {connect} from 'react-redux';

import {RootState} from '@app/types';

import {toReduxFormError} from '@common/form';
import {DispatchProps} from '@common/types';
import {isAxiosError} from '@common/utils';

import {testAuthToken, tryLogin} from '../actions';
import {isLoggedIn} from '../selectors';
import {AuthData} from '../types';

import LoginForm from './login_form';

const styles = (theme: Theme) => createStyles({
  root: {
    display: 'flex',
    alignItems: 'center',
    justifyContent: 'center',
  },
});

type LoginAppProps =
  WithStyles<typeof styles> &
  ReturnType<typeof mapStateToProps> &
  DispatchProps<typeof mapDispatchToProps>;

class LoginApp extends React.Component<LoginAppProps> {
  componentDidMount() {
    this.props.testAuthToken();
  }

  handleSubmit = async (data: AuthData) => {
    try {
      await this.props.tryLogin(data);
    } catch (err: unknown) {
      if (isAxiosError(err)) {
        throw toReduxFormError(err);
      } else {
        throw err;
      }
    }
  }

  render() {
    const {isLoggedIn, classes} = this.props;
    if (isLoggedIn === null) {
      return (
        <Modal open disableAutoFocus className={classes.root}>
          <CircularProgress size={120} />
        </Modal>
      );
    }
    return (
      <LoginForm onSubmit={this.handleSubmit} />
    );
  }
}

const mapStateToProps = (state: RootState) => ({
  isLoggedIn: isLoggedIn(state),
});

const mapDispatchToProps = {testAuthToken, tryLogin};

export default connect(mapStateToProps, mapDispatchToProps)(
  withStyles(styles)(LoginApp));
