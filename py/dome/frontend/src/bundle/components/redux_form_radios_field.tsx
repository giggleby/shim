// Copyright 2023 The ChromiumOS Authors
// Use of this source code is governed by a BSD-style license that can be
// found in the LICENSE file.

import FormControl from '@mui/material/FormControl';
import FormControlLabel from '@mui/material/FormControlLabel';
import FormHelperText from '@mui/material/FormHelperText';
import Radio, {RadioProps} from '@mui/material/Radio';
import RadioGroup from '@mui/material/RadioGroup';
import Typography from '@mui/material/Typography';

import React from 'react';
import {BaseFieldProps, Field, WrappedFieldProps} from 'redux-form';

interface RadioNameProps {
  label: string;
  value: string;
}

interface RenderRadiosFieldProps {
  radioTypes: RadioNameProps[];
  errorState?: boolean;
  radioColor?: RadioProps['color'];
  classRadio?: string;
  classLabel?: string;
}

const renderRadiosField = ({
  input,
  meta: {error},
  radioTypes,
  errorState,
  radioColor,
  classRadio,
  classLabel,
}: RenderRadiosFieldProps & WrappedFieldProps) => (
  <FormControl error={errorState} variant="standard">
    <RadioGroup
      value={input.value}
      onChange={(event: any, value: string) => input.onChange(value)}
    >
      {radioTypes.map((option: RadioNameProps, key: number) =>
        <FormControlLabel
          key={key}
          value={option.value}
          control={
            <Radio
              color={radioColor}
              className={classRadio}
            />
          }
          label={
            <Typography className={classLabel}>
              {option.label}
            </Typography>}
        />,
      )}
    </RadioGroup>
    {error && <FormHelperText>{error}</FormHelperText>}
  </FormControl>
);

type ReduxFormRadiosFieldProps =
  RenderRadiosFieldProps & BaseFieldProps<RenderRadiosFieldProps>;

const ReduxFormRadiosField: React.SFC<ReduxFormRadiosFieldProps> =
  (props) => (
    <Field<RenderRadiosFieldProps> {...props} component={renderRadiosField} />
  );

export default ReduxFormRadiosField;
