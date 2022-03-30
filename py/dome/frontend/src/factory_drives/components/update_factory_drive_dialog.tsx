// Copyright 2018 The Chromium OS Authors. All rights reserved.
// Use of this source code is governed by a BSD-style license that can be
// found in the LICENSE file.

import React from 'react';
import {connect} from 'react-redux';
import {submit} from 'redux-form';

import formDialog from '@app/form_dialog';
import project from '@app/project';
import {RootState} from '@app/types';

import FileUploadDialog, {
  SelectProps,
} from '@common/components/file_upload_dialog';
import {DispatchProps} from '@common/types';

import {startUpdateFactoryDrive} from '../actions';
import {UPDATE_FACTORY_DRIVE_FORM} from '../constants';
import {UpdateFactoryDriveFormPayload} from '../types';

import UpdateFactoryDriveForm from './update_factory_drive_form';

type UpdateFactoryDriveDialogProps =
  ReturnType<typeof mapStateToProps> & DispatchProps<typeof mapDispatchToProps>;

class UpdateFactoryDriveDialog extends React.Component<
  UpdateFactoryDriveDialogProps> {

  handleCancel = () => {
    this.props.cancelUpdate();
  }

  handleSubmitOne = ({file}: {file: File}) => {
    const {
      project,
      startUpdate,
      payload,
    } = this.props;
    const thisPayload = payload as UpdateFactoryDriveFormPayload;
    const data = {
      project,
      id: thisPayload.id,
      dirId: thisPayload.dirId,
    };
    if (thisPayload.id == null) {
      startUpdate({...data, name: file.name, file});
    } else {
      startUpdate({...data, name: thisPayload.name, file});
    }
  }

  handleSubmitMultiple = ({files}: {files: FileList}) => {
    const {
      project,
      startUpdate,
      payload,
    } = this.props;
    const thisPayload = payload as UpdateFactoryDriveFormPayload;
    const data = {
      project,
      id: thisPayload.id,
      dirId: thisPayload.dirId,
    };
    for (const f of files) {
      startUpdate({...data, name: f.name, file: f});
    }
  }

  render() {
    const {open, submitForm, payload} = this.props;
    const {multiple} = payload as UpdateFactoryDriveFormPayload;
    const selectProps: SelectProps =
      multiple ? {multiple, onSubmit: this.handleSubmitMultiple} :
        {multiple, onSubmit: this.handleSubmitOne};
    return (
      <FileUploadDialog
        open={open}
        title="Update Factory Drive"
        onCancel={this.handleCancel}
        submitForm={submitForm}
        {...selectProps}
      >
        <UpdateFactoryDriveForm />
      </FileUploadDialog>
    );
  }
}

const isFormVisible =
  formDialog.selectors.isFormVisibleFactory(UPDATE_FACTORY_DRIVE_FORM);
const getFormPayload =
  formDialog.selectors.getFormPayloadFactory(UPDATE_FACTORY_DRIVE_FORM);

const mapStateToProps = (state: RootState) => ({
  open: isFormVisible(state),
  project: project.selectors.getCurrentProject(state),
  payload: getFormPayload(state)!,
});

const mapDispatchToProps = {
  startUpdate: startUpdateFactoryDrive,
  cancelUpdate: () => formDialog.actions.closeForm(UPDATE_FACTORY_DRIVE_FORM),
  submitForm: () => submit(UPDATE_FACTORY_DRIVE_FORM),
};

export default connect(
  mapStateToProps, mapDispatchToProps)(UpdateFactoryDriveDialog);
