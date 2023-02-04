// Copyright 2023 The ChromiumOS Authors
// Use of this source code is governed by a BSD-style license that can be
// found in the LICENSE file.

import Button from '@mui/material/Button';
import red from '@mui/material/colors/red';
import List from '@mui/material/List';
import {Theme} from '@mui/material/styles';
import Typography from '@mui/material/Typography';
import {
  createStyles,
  withStyles,
  WithStyles,
} from '@mui/styles';
import React from 'react';
import {connect} from 'react-redux';
import {
  FormErrors,
  InjectedFormProps,
  reduxForm,
} from 'redux-form';

import {DispatchProps} from '@common/types';

import {resetDuplicateBundleResource} from '../actions';
import {FileList, RequireUserAction, Resource} from '../types';

import ReduxFormRadiosField from './redux_form_radios_field';

const styles = (theme: Theme) => createStyles({
  duplicateResourceLists: {
    backgroundColor: red[100],
    marginTop: theme.spacing(1),
    marginBottom: theme.spacing(1),
    paddingTop: theme.spacing(1),
    paddingBottom: theme.spacing(1),
    paddingLeft: theme.spacing(1),
    paddingRight: theme.spacing(1),
  },
  duplicateResourceItem: {
    padding: theme.spacing(1),
    paddingLeft: theme.spacing(2),
  },
  duplicateResourceItemLabel: {
    fontSize: '0.8125rem',
  },
  duplicateResourceButton: {
    fontSize: '0.75rem',
    marginTop: theme.spacing(1),
    marginRight: theme.spacing(1),
  },
});

interface FormProps {
  classes: any;
  radioTypes: any;
  resourceType: string;
}

interface FormData {
  selectedDuplicate: string;
}

const validate = (values: FormData) => {
  const errors: FormErrors<FormData> = {};
  if (!values.selectedDuplicate) {
    errors.selectedDuplicate = 'Required';
  }
  return errors;
};

const selectedDuplicate: any = [];
const handleRadioChange = (value: string, index: string) => {
  selectedDuplicate[index] = value;
};

const InnerFormComponent: React.SFC<
  FormProps & InjectedFormProps<FormData, FormProps>> =
  ({classes, radioTypes, resourceType, handleSubmit}) => (
    <form onSubmit={handleSubmit}>
      <div className={classes.width}>
        <ReduxFormRadiosField
          name="selectedDuplicate"
          radioColor="error"
          radioTypes={radioTypes}
          classRadio={classes.duplicateResourceItem}
          classLabel={classes.duplicateResourceItemLabel}
          errorState
          onChange={
            (e, value) =>
              handleRadioChange(value, resourceType)
          }
        />
      </div>
      <Button
        className={classes.duplicateResourceButton}
        color="error"
        size="small"
        type="submit"
        variant="contained"
      >
        Confirm
      </Button>
    </form>
  );

const InnerForm = reduxForm<FormData, FormProps>({
  validate,
})(InnerFormComponent);

interface DuplicateResourceFormOwnProps {
  form: string;
  resource: Resource;
  resourceType: string;
  duplicate: RequireUserAction;
  onSubmit: (values: FormData) => any;
}

type DuplicateResourceFormProps =
  DuplicateResourceFormOwnProps &
  WithStyles<typeof styles> &
  DispatchProps<typeof mapDispatchToProps>;

class DuplicateResourceForm
  extends React.Component<DuplicateResourceFormProps> {
  render() {
    const {
      form,
      resource,
      resourceType,
      duplicate,
      onSubmit,
      classes,
    } = this.props;
    const radioTypes: any = [];
    duplicate.fileList.map((option: FileList) => {
      radioTypes.push({
        label: option.version,
        value: option.file,
      });
    });
    return (
      <List className={classes.duplicateResourceLists}>
        <Typography variant="body2">
          Multiple "{resource.type}" found,
          please choose only one:
        </Typography>
        <InnerForm
          form={form}
          onSubmit={onSubmit}
          initialValues={{selectedDuplicate: ''}}
          classes={classes}
          resourceType={resourceType}
          radioTypes={radioTypes}
        />
      </List>
    );
  }
}

const mapDispatchToProps = {
  resetDuplicateBundleResource,
};

export default connect(null, mapDispatchToProps)(
  withStyles(styles)(DuplicateResourceForm));
