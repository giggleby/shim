// Copyright 2017 The ChromiumOS Authors
// Use of this source code is governed by a BSD-style license that can be
// found in the LICENSE file.

import Button from '@mui/material/Button';
import Card from '@mui/material/Card';
import CardActions from '@mui/material/CardActions';
import CardContent from '@mui/material/CardContent';
import FormHelperText from '@mui/material/FormHelperText';
import {Theme} from '@mui/material/styles';
import Typography from '@mui/material/Typography';
import {
  createStyles,
  withStyles,
  WithStyles,
} from '@mui/styles';
import React from 'react';
import {InjectedFormProps, reduxForm} from 'redux-form';

import ReduxFormTextField from '@common/components/redux_form_text_field';

import {AuthData} from '../types';

const styles = (theme: Theme) => createStyles({
  actions: {
    justifyContent: 'flex-end',
  },
});

type LoginFormProps =
  InjectedFormProps<AuthData> & WithStyles<typeof styles>;

const LoginForm: React.SFC<LoginFormProps> =
  ({handleSubmit, classes, error}) => (
    <form onSubmit={handleSubmit}>
      <Card>
        <CardContent>
          <Typography variant="h5">
            Login to continue
          </Typography>
          <ReduxFormTextField
            name="username"
            label="Username"
            type="text"
          />
          <ReduxFormTextField
            name="password"
            label="Password"
            type="password"
          />
          {error && <FormHelperText error>{error}</FormHelperText>}
        </CardContent>
        <CardActions className={classes.actions}>
          <Button color="primary" type="submit">Login</Button>
        </CardActions>
      </Card>
    </form>
  );

export default reduxForm<AuthData>({form: 'login'})(
  withStyles(styles)(LoginForm));
