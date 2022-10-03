// Copyright 2016 The Chromium OS Authors. All rights reserved.
// Use of this source code is governed by a BSD-style license that can be
// found in the LICENSE file.

import Button from '@mui/material/Button';
import Chip from '@mui/material/Chip';
import Dialog from '@mui/material/Dialog';
import DialogActions from '@mui/material/DialogActions';
import DialogContent from '@mui/material/DialogContent';
import DialogTitle from '@mui/material/DialogTitle';
import Tooltip from '@mui/material/Tooltip';
import Typography from '@mui/material/Typography';
import React from 'react';
import {connect} from 'react-redux';
import {
  InjectedFormProps,
  reduxForm,
  submit,
} from 'redux-form';

import formDialog from '@app/form_dialog';
import {Project} from '@app/project/types';
import {RootState} from '@app/types';

import ReduxFormTextField from '@common/components/redux_form_text_field';
import {HiddenSubmitButton, parseNumber, validateRequired} from '@common/form';
import {DispatchProps} from '@common/types';

import {ENABLE_UMPIRE_FORM} from '../constants';
import {getPorts} from '../selectors';
import {Port, PortResponse} from '../types';

interface FormProps {
  hasExisting: boolean;
  projectName: string;
}

interface FormData {
  umpirePort: number;
  ports: PortResponse;
}

/**
 * Check whether the current umpire port overlaps with the ports of other
 * projects, if overlap, then return the project name which is overlap.
 * @param currentUmpirePort The current umpire port of the project.
 * @param ports Includes data for maxPortOffset and allPorts.
 */
const checkUmpirePortOverlap = (currentUmpirePort: number,
                                ports: PortResponse) => {
  const maxPortOffset = ports.maxPortOffset;
  let project_name = null;
  ports.allPorts.forEach((port: Port) => {
    const minPort = port.umpirePort - maxPortOffset;
    const maxPort = port.umpirePort + maxPortOffset;
    if (currentUmpirePort >= minPort && currentUmpirePort <= maxPort) {
      project_name = port.name;
    }
  });
  return project_name;
};

const validate = (values: FormData) => {
  const errors: any = {};
  if (values.ports) {
    const project_name = checkUmpirePortOverlap(values.umpirePort,
                                                values.ports);
    if (project_name !== null) {
      errors.umpirePort =
        `Port range will overlap with ${project_name} project`;
    }
  }
  return errors;
};

const InnerFormComponent: React.SFC<
  FormProps & InjectedFormProps<FormData, FormProps>> =
  ({hasExisting, projectName, handleSubmit}) => (
    <form onSubmit={handleSubmit}>
      {hasExisting ? (
        `Umpire container for ${projectName} already exists,` +
        ' it would be added to Dome.'
      ) : (
        <ReduxFormTextField
          name="umpirePort"
          label="port"
          type="number"
          parse={parseNumber}
          validate={[
            validateRequired,
          ]}
        />
      )}
      <HiddenSubmitButton />
    </form>
  );

const InnerForm = reduxForm<FormData, FormProps>({
  form: ENABLE_UMPIRE_FORM,
  validate,
})(InnerFormComponent);

interface EnableUmpireFormOwnProps {
  project: Project;
  ports: PortResponse;
  onCancel: () => any;
  onSubmit: (values: FormData) => any;
}

type EnableUmpireFormProps =
  EnableUmpireFormOwnProps &
  ReturnType<typeof mapStateToProps> &
  DispatchProps<typeof mapDispatchToProps>;

const EnableUmpireForm: React.SFC<EnableUmpireFormProps> = ({
  open,
  onSubmit,
  onCancel,
  submitForm,
  project,
  ports,
}) => {
  const initialValues = {
    umpirePort: project.umpirePort || 8080,
    ports: ports,
  };
  const hasExisting = project.hasExistingUmpire;
  return (
    <Dialog open={open} onClose={onCancel}>
      <DialogTitle>Enable Umpire</DialogTitle>
      <DialogContent>
        <Typography>Ports are already use in</Typography>
        {
          ports.allPorts?.map((port: Port) => (
            <Tooltip title={port.name}>
              <Chip
                label={
                  `${port.umpirePort}~${port.umpirePort + ports.maxPortOffset}`
                }
                size="small"
                sx={{marginRight: 1, marginBottom: 1}}
              />
            </Tooltip>
          ))
        }
        <InnerForm
          onSubmit={onSubmit}
          initialValues={initialValues}
          projectName={project.name}
          hasExisting={hasExisting}
        />
      </DialogContent>
      <DialogActions>
        <Button color="primary" onClick={submitForm}>
          {hasExisting ? 'Add' : 'Create'}
        </Button>
        <Button onClick={onCancel}>Cancel</Button>
      </DialogActions>
    </Dialog>
  );
};

const isFormVisible =
  formDialog.selectors.isFormVisibleFactory(ENABLE_UMPIRE_FORM);

const mapStateToProps = (state: RootState) => ({
  open: isFormVisible(state),
  ports: getPorts(state),
});

const mapDispatchToProps = {
  submitForm: () => submit(ENABLE_UMPIRE_FORM),
};

export default connect(mapStateToProps, mapDispatchToProps)(EnableUmpireForm);
