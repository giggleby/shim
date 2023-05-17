// Copyright 2023 The ChromiumOS Authors
// Use of this source code is governed by a BSD-style license that can be
// found in the LICENSE file.

import Alert from '@mui/material/Alert';
import AlertTitle from '@mui/material/AlertTitle';
import Button from '@mui/material/Button';
import Stack from '@mui/material/Stack';
import {Theme} from '@mui/material/styles';
import Typography from '@mui/material/Typography';
import {
  createStyles,
  withStyles,
  WithStyles,
} from '@mui/styles';
import React from 'react';
import {connect} from 'react-redux';

import CodeSnippet from '@app/common/components/code_snippet';
import {disableVersionCheck} from '@app/config/actions';
import {isVersionCheckEnabled} from '@app/config/selectors';
import {RootState} from '@app/types';

import {DispatchProps} from '@common/types';

import {fetchDomeInfo} from '../actions';
import {getDomeInfo} from '../selectors';

const styles = (theme: Theme) => createStyles({
  alert: {
    marginBottom: theme.spacing(2),
    '& .MuiAlert-message': {
      width: '100%',
    },
  },
  button: {
    width: '150px',
    textTransform: 'none',
  },
});

type DomeAppVersionAlertProps =
  WithStyles<typeof styles> &
  ReturnType<typeof mapStateToProps> &
  DispatchProps<typeof mapDispatchToProps>;

class DomeAppVersionAlert extends React.Component<DomeAppVersionAlertProps> {
  render() {
    const {
      domeInfo,
      isVersionCheckEnabled,
      disableVersionCheck,
      classes,
    } = this.props;
    const latestVersion = Number(domeInfo?.dockerImageLatestVersion!);
    const currentVersion = Number(domeInfo?.dockerImageTimestamp!);
    const codeArr = [
      './cros_docker.sh update',
      './cros_docker.sh pull',
      './cros_docker.sh install',
      './cros_docker.sh run',
    ];
    return (
      <>
        {isVersionCheckEnabled && (latestVersion > currentVersion) &&
          <Alert severity="info" className={classes.alert}>
            <AlertTitle>
              Get the latest DOME updates available for you
              (version <code>{latestVersion}</code>)
            </AlertTitle>
            <Typography variant="body2">
              Please do following commands:
            </Typography>
            <CodeSnippet
              value={codeArr.join(' && ')}
              html={codeArr.join(' && <br />')}
            />
            <Stack direction="row" justifyContent="flex-end">
              <Button
                color="primary"
                size="small"
                className={classes.button}
                onClick={disableVersionCheck}
              >
                Don't show again
              </Button>
            </Stack>
          </Alert>
        }
      </>
    );
  }
}

const mapStateToProps = (state: RootState) => ({
  domeInfo: getDomeInfo(state),
  isVersionCheckEnabled: isVersionCheckEnabled(state),
});

const mapDispatchToProps = {
  fetchDomeInfo,
  disableVersionCheck,
};

export default connect(mapStateToProps, mapDispatchToProps)(
  withStyles(styles)(DomeAppVersionAlert));
