// Copyright 2023 The ChromiumOS Authors
// Use of this source code is governed by a BSD-style license that can be
// found in the LICENSE file.

import FormControl from "@mui/material/FormControl";
import FormControlLabel from "@mui/material/FormControlLabel";
import Radio from "@mui/material/Radio";
import RadioGroup from "@mui/material/RadioGroup";
import React from "react";

/** The settings for each radio option. */
export interface RadioOption {
  /**
   * The display string of a radio option.
   */
  label: string;
  /**
   * The value corresponding to the display string.
   */
  value: string | boolean | number;
}

/** The props to configure `RadioGroupField`. */
export interface RadioGroupFieldProps {
  /**
   * The value that will be used as the *Value* key.
   */
  value: boolean | string;
  /**
   * The settings for each radio option.
   */
  options: RadioOption[];
  /**
   * The function for handling state change.
   * @param value The new value.
   * @returns void
   */
  onChange: (value: string | boolean | number) => void;
}

/**
 * The component that allows the user to select one option from a set.
 * @param {RadioGroupFieldProps} props The props to configure the component.
 */
export function RadioGroupField(
  props: RadioGroupFieldProps,
): React.ReactElement {
  const { value, options, onChange } = props;
  const handleChange = (event: React.ChangeEvent<HTMLInputElement>) => {
    const matchedOption = options.find(
      (option) => option.value.toString() === event.target.value,
    );
    const selectedValue = matchedOption?.value ?? event.target.value;
    // TODO: Show some warning if we fall backed to event.target.value.
    //       It's not likely for `matchedOption` to be undefined and we
    //       had to fall back to use `event.target.value`.

    onChange(selectedValue);
  };

  return (
    <FormControl>
      <RadioGroup
        row
        value={value}
        onChange={handleChange}
      >
        {options.map((option) => {
          return (
            <FormControlLabel
              key={option.label}
              value={option.value}
              control={<Radio />}
              label={option.label}
            />
          );
        })}
      </RadioGroup>
    </FormControl>
  );
}
