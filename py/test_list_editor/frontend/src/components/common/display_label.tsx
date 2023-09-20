// Copyright 2023 The ChromiumOS Authors
// Use of this source code is governed by a BSD-style license that can be
// found in the LICENSE file.

import Typography, { TypographyProps } from "@mui/material/Typography";
import React from "react";

export interface DisplayLabelProps extends TypographyProps {
  /**
   * The string that will be used as the *Label*.
   */
  label: string;
}

/**
 * The component for displaying a label.
 *
 * To overwrite the default settings, pass in props defined in `TypographyProps`.
 * @param {DisplayLabelProps} props The props to configure the component.
 * @returns The component.
 */
export function DisplayLabel(props: DisplayLabelProps): React.ReactElement {
  const { label, ...typographyProps } = props;
  return (
    <Typography
      variant="body1"
      color="text.secondary"
      {...typographyProps}
    >
      {label}
    </Typography>
  );
}
