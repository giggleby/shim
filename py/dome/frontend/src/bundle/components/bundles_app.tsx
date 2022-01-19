// Copyright 2016 The Chromium OS Authors. All rights reserved.
// Use of this source code is governed by a BSD-style license that can be
// found in the LICENSE file.

import Fab from '@mui/material/Fab';
import Portal from '@mui/material/Portal';
import AddIcon from '@mui/icons-material/Add';
import React from 'react';
import {connect} from 'react-redux';

import formDialog from '@app/form_dialog';

import {DispatchProps} from '@common/types';

import {UPLOAD_BUNDLE_FORM} from '../constants';

import BundleList from './bundle_list';
import ResourcesGarbageCollectionButton from './resources_gc';
import UpdateResourceDialog from './update_resource_dialog';
import UploadBundleDialog from './upload_bundle_dialog';

interface BundlesAppOwnProps {
  overlay: Element | null;
}

type BundlesAppProps =
  BundlesAppOwnProps & DispatchProps<typeof mapDispatchToProps>;

const BundlesApp: React.SFC<BundlesAppProps> =
  ({overlay, openUploadNewBundleForm}) => (
    <>
      <BundleList />

      <UploadBundleDialog />
      <UpdateResourceDialog />

      {/* upload button */}
      {overlay &&
        <>
          <Portal container={overlay}>
            <Fab
              color="primary"
              title="Upload Factory Bundle (zip or {gzip|bzip2|xz} compressed tarball)"
              onClick={openUploadNewBundleForm}
            >
              <AddIcon />
            </Fab>
          </Portal>
          <Portal container={overlay}>
            <ResourcesGarbageCollectionButton />
          </Portal>
        </>
      }
    </>
  );

const mapDispatchToProps = {
  openUploadNewBundleForm: () => (
    formDialog.actions.openForm(UPLOAD_BUNDLE_FORM)
  ),
};

export default connect(null, mapDispatchToProps)(BundlesApp);
