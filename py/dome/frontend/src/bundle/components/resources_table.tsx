// Copyright 2016 The ChromiumOS Authors
// Use of this source code is governed by a BSD-style license that can be
// found in the LICENSE file.

import dateFormat from 'dateformat';

import Download from '@mui/icons-material/GetApp';
import Update from '@mui/icons-material/Publish';
import WarningIcon from '@mui/icons-material/Warning';
import grey from '@mui/material/colors/grey';
import orange from '@mui/material/colors/orange';
import IconButton from '@mui/material/IconButton';
import {Theme} from '@mui/material/styles';
import Typography from '@mui/material/Typography';
import {
  createStyles,
  withStyles,
  WithStyles,
} from '@mui/styles';
import classNames from 'classnames';
import React from 'react';
import {connect} from 'react-redux';

import formDialog from '@app/form_dialog';

import {thinScrollBarX} from '@common/styles';
import {DispatchProps} from '@common/types';

import {downloadResource, resetDuplicateBundleResource} from '../actions';
import {DUPLICATE_RESEOURCE_FORM, UPDATE_RESOURCE_FORM} from '../constants';
import {Bundle, RequireUserAction} from '../types';

import DuplicateResourceForm from './duplicate_resource_form';

const styles = (theme: Theme) => createStyles({
  root: {
    display: 'grid',
    gridTemplateColumns: '1fr 2fr auto',
    width: '100%',
  },
  cell: {
    padding: theme.spacing(1),
    display: 'flex',
    alignItems: 'center',
    borderBottom: `1px solid ${grey[300]}`,
    fontSize: theme.typography.pxToRem(13),
    ...thinScrollBarX,
  },
  actionColumn: {
    justifyContent: 'center',
  },
  small: {
    color: orange[700],
  },
  warningIcon: {
    fontSize: '0.9rem',
    color: orange[700],
    marginRight: '3px',
  },
  width: {
    width: '100%',
  },
});

interface ResourceTableOwnProps {
  bundle: Bundle;
  projectName: string;
}

type ResourceTableProps =
  ResourceTableOwnProps &
  WithStyles<typeof styles> &
  DispatchProps<typeof mapDispatchToProps>;

class ResourceTable extends React.Component<ResourceTableProps> {
  render() {
    const {
      bundle: {name, resources, requireUserAction},
      projectName,
      openUpdateResourceForm,
      resetDuplicateBundleResource,
      classes,
    } = this.props;

    const downloadableResources =
        /^toolkit(_config)?|hwid|firmware|complete|netboot_.*|lsb_factory$/;

    return (
      <div className={classes.root}>
        <div className={classes.cell}>
          <Typography variant="caption">
            resource
          </Typography>
        </div>
        <div className={classes.cell}>
          <Typography variant="caption">
            version
          </Typography>
        </div>
        <div
          className={classNames(classes.cell, classes.actionColumn)}
        >
          <Typography variant="caption">
            actions
          </Typography>
        </div>
        {Object.keys(resources).sort().map((resourceType: string) => {
          const resource = resources[resourceType];
          let duplicates: RequireUserAction[] = [];
          if (resourceType in requireUserAction) {
            duplicates = requireUserAction[resourceType].filter((obj: any) => {
                return obj.type === 'duplicate';
            });
          }
          return (
            <React.Fragment key={resource.type}>
              <div className={classes.cell}>
                {resource.type} ({resourceNameToFileType[resource.type]})
              </div>
              <div className={classes.cell}>
                <div className={classes.width}>
                  {resource.version}
                  {(resource.information) ?
                    <div>
                      {resource.information}
                    </div>
                  : <></>}
                  {(resource.warningMessage) ?
                    JSON.parse(resource.warningMessage).map(
                      (warningMessage: string, index: number) => {
                      return (
                        <div key={index} className={classes.small}>
                          <WarningIcon className={classes.warningIcon} />
                          {warningMessage}
                        </div>
                      );
                    })
                  : <></>}
                  {duplicates.length > 0 &&
                   duplicates.map((duplicate: RequireUserAction, key: number) =>
                    <DuplicateResourceForm
                      key={key}
                      form={
                        `${DUPLICATE_RESEOURCE_FORM}.${name}.${resourceType}`}
                      resource={resource}
                      resourceType={resourceType}
                      duplicate={duplicate}
                      onSubmit={({selectedDuplicate}: any) => {
                        const regexp = /\d{14}$/;
                        const note = `Updated "${resourceType}" type resource`;
                        let bundleName = name;
                        const timeString = dateFormat(new Date(),
                                                      'yyyymmddHHMMss');
                        if (regexp.test(name)) {
                          bundleName = name.replace(regexp, timeString);
                        } else {
                          if (name === 'empty') {
                            bundleName = projectName;
                          }
                          bundleName += '-' + timeString;
                        }
                        resetDuplicateBundleResource(projectName, name,
                          bundleName, note, resource.type, selectedDuplicate);
                      }}
                    />,
                  )}
                </div>
              </div>
              <div className={classes.cell}>
                <IconButton
                  onClick={
                    () => openUpdateResourceForm(name, resourceType,
                                                 resource.type)
                  }
                >
                  <Update />
                </IconButton>

                {(!downloadableResources.test(resource.type) ||
                  resource.version === 'N/A') ?
                  <span /> :
                  <IconButton
                    onClick={
                        () => this.props.downloadResource(
                        projectName, name, resource.type)}
                  >
                    <Download />
                  </IconButton>}
              </div>
            </React.Fragment>
          );
        })}
      </div>
    );
  }
}

const resourceNameToFileType: Record<string, string> = {
    complete: '*.sh',
    firmware: 'chromeos-firmwareupdate',
    hwid: 'hwid_v3_bundle_*.sh',
    netboot_cmdline: 'cmdline',
    netboot_firmware: '*.net.bin',
    netboot_kernel: 'vmlinu*',
    project_config: '*.tar.gz',
    release_image: '*.bin',
    test_image: '*.bin',
    toolkit: '*.run',
};

const mapDispatchToProps = {
  downloadResource,
  openUpdateResourceForm:
    (bundleName: string, resourceKey: string, resourceType: string) => (
      formDialog.actions.openForm(
        UPDATE_RESOURCE_FORM,
        // TODO(littlecvr): resourceKey are actually the same, but
        //                  resourceKey is CamelCased, resourceType is
        //                  lowercase_separated_by_underscores. We should
        //                  probably normalize the data in store so we don't
        //                  have to pass both resourceKey and resourceType
        //                  into it.
        {bundleName, resourceKey, resourceType})
    ),
  resetDuplicateBundleResource,
};

export default connect(null, mapDispatchToProps)(
  withStyles(styles)(ResourceTable));
