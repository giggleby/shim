// Copyright 2023 The ChromiumOS Authors
// Use of this source code is governed by a BSD-style license that can be
// found in the LICENSE file.

import Grid2 from "@mui/material/Unstable_Grid2";
import React from "react";

export interface LabeledInputProps {
  /**
   * The component of the label.
   */
  label: React.ReactElement;
  /**
   * The component of the input field.
   */
  inputField: React.ReactElement;
  /**
   * The width of the flexbox size for the label component.
   */
  labelWidth: number;
  /**
   * The width of the flexbox size for the input field component.
   */
  inputWidth: number;
}

/**
 * A component that displays a label alongside the input field component.
 * @param {LabeledInputProps} props The props to configure the component.
 */
export function LabeledInput(props: LabeledInputProps): React.ReactElement {
  const { label, labelWidth, inputField, inputWidth } = props;
  return (
    <Grid2
      container
      spacing="16px"
    >
      <Grid2
        display="flex"
        justifyContent="right"
        alignItems="center"
        xs={labelWidth}
      >
        {label}
      </Grid2>
      <Grid2 xs={inputWidth}>{inputField}</Grid2>
    </Grid2>
  );
}
