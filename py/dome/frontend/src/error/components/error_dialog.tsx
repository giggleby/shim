// Copyright 2017 The Chromium OS Authors. All rights reserved.
// Use of this source code is governed by a BSD-style license that can be
// found in the LICENSE file.

import Button from '@mui/material/Button';
import Dialog from '@mui/material/Dialog';
import DialogActions from '@mui/material/DialogActions';
import DialogContent from '@mui/material/DialogContent';
import {
  createStyles,
  withStyles,
  WithStyles,
} from '@mui/styles';
import React from 'react';
import {connect} from 'react-redux';

import {RootState} from '@app/types';

import {DispatchProps} from '@common/types';

import {hideErrorDialog} from '../actions';
import {getErrorMessage, isErrorDialogShown} from '../selectors';

const styles = createStyles({
  textarea: {
    width: '100%',
    height: '20em',
    whiteSpace: 'pre',
  },
});

type ErrorDialogProps =
  WithStyles<typeof styles> &
  ReturnType<typeof mapStateToProps> &
  DispatchProps<typeof mapDispatchToProps>;

const ErrorDialog: React.SFC<ErrorDialogProps> =
  ({message, show, hideErrorDialog, classes}) => (
    <Dialog maxWidth="md" open={show} onClose={hideErrorDialog}>
      <DialogContent>
        An error has occured, please copy the following error message, and
        contact the ChromeOS factory team.
        <textarea
          disabled
          className={classes.textarea}
          value={message}
        />
      </DialogContent>
      <DialogActions>
        <Button color="primary" onClick={hideErrorDialog}>
          close
        </Button>
      </DialogActions>
    </Dialog>
  );

const mapStateToProps = (state: RootState) => ({
  show: isErrorDialogShown(state),
  message: getErrorMessage(state),
});

const mapDispatchToProps = {hideErrorDialog};

export default connect(mapStateToProps, mapDispatchToProps)(
  withStyles(styles)(ErrorDialog));
