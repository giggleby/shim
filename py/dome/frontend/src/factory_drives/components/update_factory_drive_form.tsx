// Copyright 2018 The Chromium OS Authors. All rights reserved.
// Use of this source code is governed by a BSD-style license that can be
// found in the LICENSE file.

import React from 'react';
import {
  InjectedFormProps,
  reduxForm,
} from 'redux-form';

import {UPDATE_FACTORY_DRIVE_FORM} from '../constants';

class UpdateFactoryDriveForm extends React.Component<
  InjectedFormProps> {

  render() {
    return (
      <>
      </>
    );
  }
}

export default reduxForm<{}, {}>({
  form: UPDATE_FACTORY_DRIVE_FORM,
})(UpdateFactoryDriveForm);
