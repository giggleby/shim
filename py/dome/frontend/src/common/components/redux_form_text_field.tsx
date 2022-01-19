// Copyright 2018 The Chromium OS Authors. All rights reserved.
// Use of this source code is governed by a BSD-style license that can be
// found in the LICENSE file.

import {InputLabelProps} from '@mui/material/InputLabel';
import TextField from '@mui/material/TextField';
import React from 'react';
import {BaseFieldProps, Field, WrappedFieldProps} from 'redux-form';

interface RenderTextFieldProps {
  label: string;
  type?: string;
  ignoreTouch?: boolean;
  placeholder?: string;
  margin?: 'dense' | 'normal' | 'none';
  InputLabelProps?: Partial<InputLabelProps>;
  select?: boolean;
  disabled?: boolean;
}

const renderTextField = ({
  input,
  meta: {error, touched},
  ignoreTouch,
  ...props
}: RenderTextFieldProps & WrappedFieldProps) => (
  <TextField
    fullWidth
    error={!!((touched || ignoreTouch) && error)}
    helperText={(touched || ignoreTouch) && error}
    margin="normal"
    {...input}
    {...props}
  />
);

export type ReduxFormTextFieldProps =
  RenderTextFieldProps & BaseFieldProps<RenderTextFieldProps>;

const ReduxFormTextField: React.SFC<ReduxFormTextFieldProps> =
  (props) => (
    <Field<RenderTextFieldProps> {...props} component={renderTextField} />
  );

export default ReduxFormTextField;
