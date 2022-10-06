// Copyright 2018 The ChromiumOS Authors
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
  InjectedFormProps,
  reduxForm,
  submit,
} from 'redux-form';

import formDialog from '@app/form_dialog';
import project from '@app/project';
import {RootState} from '@app/types';

import ReduxFormTextField from '@common/components/redux_form_text_field';
import {HiddenSubmitButton} from '@common/form';
import {DispatchProps} from '@common/types';

import {startRenameFactoryDrive} from '../actions';
import {RENAME_FACTORY_DRIVE_FORM} from '../constants';
import {RenameRequest} from '../types';

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
  form: RENAME_FACTORY_DRIVE_FORM,
})(InnerFormComponent);

type RenameFactoryDriveFormProps =
  ReturnType<typeof mapStateToProps> &
  DispatchProps<typeof mapDispatchToProps>;

class RenameFactoryDriveForm
  extends React.Component<RenameFactoryDriveFormProps> {
  render() {
    const {open, cancelRename, renameFactoryDrive, submitForm} = this.props;
    const payload = this.props.payload as RenameRequest;
    const initialValues = {
      id: payload.id,
      name: payload.name,
    };
    return (
      <Dialog open={open} onClose={cancelRename}>
        <DialogTitle>Rename Factory Drive</DialogTitle>
        <DialogContent>
          <InnerForm
            onSubmit={renameFactoryDrive}
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
  formDialog.selectors.isFormVisibleFactory(RENAME_FACTORY_DRIVE_FORM);
const getFormPayload =
  formDialog.selectors.getFormPayloadFactory(RENAME_FACTORY_DRIVE_FORM);

const mapStateToProps = (state: RootState) => ({
  open: isFormVisible(state),
  project: project.selectors.getCurrentProject(state),
  payload: getFormPayload(state)!,
});

const mapDispatchToProps = {
  submitForm: () => submit(RENAME_FACTORY_DRIVE_FORM),
  cancelRename: () => formDialog.actions.closeForm(RENAME_FACTORY_DRIVE_FORM),
  renameFactoryDrive: startRenameFactoryDrive,
};

export default connect(
  mapStateToProps, mapDispatchToProps)(RenameFactoryDriveForm);
