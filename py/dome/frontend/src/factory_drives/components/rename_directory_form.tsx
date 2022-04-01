// Copyright 2018 The Chromium OS Authors. All rights reserved.
// Use of this source code is governed by a BSD-style license that can be
// found in the LICENSE file.

import Button from '@mui/material/Button';
import Dialog from '@mui/material/Dialog';
import DialogActions from '@mui/material/DialogActions';
import DialogContent from '@mui/material/DialogContent';
import DialogTitle from '@mui/material/DialogTitle';
import React from 'react';
import {connect} from 'react-redux';
import {
  FormErrors,
  InjectedFormProps,
  reduxForm,
  submit,
} from 'redux-form';

import formDialog from '@app/form_dialog';
import project from '@app/project';
import {RootState} from '@app/types';

import ReduxFormTextField from '@common/components/redux_form_text_field';
import {HiddenSubmitButton, validateDirectoryName} from '@common/form';
import {DispatchProps} from '@common/types';

import {startRenameDirectory} from '../actions';
import {RENAME_DIRECTORY_FORM} from '../constants';
import {RenameRequest} from '../types';

const validate = (values: RenameRequest) => {
  const errors: FormErrors<RenameRequest> = {};
  if (!validateDirectoryName(values.name)) {
    errors['name'] = 'Invalid directory name. It should only contain: A-Z, a-z, 0-9, -, _';
  }
  return errors;
};

const InnerFormComponent: React.SFC<InjectedFormProps<RenameRequest>> =
  ({handleSubmit}) => (
    <form onSubmit={handleSubmit}>
      <ReduxFormTextField
        name="name"
        label="name"
        type="string"
      />
      <HiddenSubmitButton />
    </form>
  );

const InnerForm = reduxForm<RenameRequest>({
  form: RENAME_DIRECTORY_FORM,
  validate,
})(InnerFormComponent);

type RenameDirectoryFormProps =
  ReturnType<typeof mapStateToProps> &
  DispatchProps<typeof mapDispatchToProps>;

class RenameDirectoryForm extends React.Component<RenameDirectoryFormProps> {
  render() {
    const {open, cancelRename, renameDirectory, submitForm} = this.props;
    const payload = this.props.payload as RenameRequest;
    const initialValues = {
      id: payload.id,
      name: payload.name,
    };
    return (
      <Dialog open={open} onClose={cancelRename}>
        <DialogTitle>Rename Directory</DialogTitle>
        <DialogContent>
          <InnerForm
            onSubmit={renameDirectory}
            initialValues={initialValues}
          />
        </DialogContent>
        <DialogActions>
          <Button color="primary" onClick={submitForm}>Rename</Button>
          <Button onClick={cancelRename}>Cancel</Button>
        </DialogActions>
      </Dialog>
    );
  }
}

const isFormVisible =
  formDialog.selectors.isFormVisibleFactory(RENAME_DIRECTORY_FORM);
const getFormPayload =
  formDialog.selectors.getFormPayloadFactory(RENAME_DIRECTORY_FORM);

const mapStateToProps = (state: RootState) => ({
  open: isFormVisible(state),
  project: project.selectors.getCurrentProject(state),
  payload: getFormPayload(state)!,
});

const mapDispatchToProps = {
  submitForm: () => submit(RENAME_DIRECTORY_FORM),
  cancelRename: () => formDialog.actions.closeForm(RENAME_DIRECTORY_FORM),
  renameDirectory: startRenameDirectory,
};

export default connect(
  mapStateToProps, mapDispatchToProps)(RenameDirectoryForm);
