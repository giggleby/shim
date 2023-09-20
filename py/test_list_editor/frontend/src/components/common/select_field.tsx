// Copyright 2023 The ChromiumOS Authors
// Use of this source code is governed by a BSD-style license that can be
// found in the LICENSE file.

import MenuItem from "@mui/material/MenuItem";
import Select, { SelectChangeEvent } from "@mui/material/Select";
import React from "react";

/** The settings for each select item. */
export interface SelectOption {
  /**
   * The display string of a item.
   */
  label: string;
  /**
   * The value corresponding to the display string.
   */
  value: string;
}

/** The props to configure `SelectField`. */
export interface SelectFieldProps {
  /**
   * The value that will be used as the *Value* key.
   */
  value: string;
  /**
   * The settings for list options.
   */
  options: SelectOption[];
  /**
   * The function for handling state change.
   * @param value The new value.
   * @returns void
   */
  onChange: (value: string) => void;
}

/**
 * The component that allows the user to select one option from a list.
 * @param {SelectFieldProps} props The props to configure the component.
 */
export function SelectField(props: SelectFieldProps): React.ReactElement {
  const { value, options, onChange } = props;
  const handleChange = (event: SelectChangeEvent) => {
    onChange(event.target.value);
  };

  return (
    <Select
      value={value}
      onChange={handleChange}
    >
      {options.map((option) => {
        return (
          <MenuItem
            key={`${option.value}-menuitem`}
            value={option.value}
          >
            {option.label}
          </MenuItem>
        );
      })}
    </Select>
  );
}
