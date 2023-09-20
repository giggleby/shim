// Copyright 2023 The ChromiumOS Authors
// Use of this source code is governed by a BSD-style license that can be
// found in the LICENSE file.

import TextField from "@mui/material/TextField";
import React from "react";
import { JSONValidation, useJSONValidation } from "../../hooks/json";

/** The props to configure `StringTextField`. */
export interface StringTextFieldProps {
  /**
   * The value that will be used as the *Value* key.
   */
  value: string;
  /**
   * Validate the string to be a JSON object using `useJSONValidation` hook.
   */
  validateJSON: boolean;
  /**
   * The function for handling state change.
   * @param value The new value.
   * @returns void
   */
  onChange: (value: string) => void;
}

/**
 * The component that to show a key and a string input field.
 * @param {StringTextFieldProps} props The props to configure the component.
 */
export function StringTextField(
  props: StringTextFieldProps,
): React.ReactElement {
  const { value, validateJSON, onChange } = props;
  const { valid, statusText }: JSONValidation = useJSONValidation(value);
  return (
    <TextField
      value={value}
      variant="standard"
      onChange={(
        event: React.ChangeEvent<HTMLTextAreaElement | HTMLInputElement>,
      ) => {
        onChange(event.target.value);
      }}
      multiline
      fullWidth
      error={validateJSON && !valid}
      helperText={validateJSON ? statusText : ""}
    />
  );
}
