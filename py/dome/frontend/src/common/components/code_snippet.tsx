// Copyright 2023 The ChromiumOS Authors
// Use of this source code is governed by a BSD-style license that can be
// found in the LICENSE file.

import NoSsr from '@mui/base/NoSsr';
import Box from '@mui/material/Box';
import indigo from '@mui/material/colors/indigo';
import {Theme} from '@mui/material/styles';
import {
  createStyles,
  withStyles,
  WithStyles,
} from '@mui/styles';
import React from 'react';
import {connect} from 'react-redux';

import CodeCopyButton from './code_copy_button';

const styles = (theme: Theme) => createStyles({
  outsideBox: {
    position: 'relative',
    fontFamily: 'monospace',
  },
  insideBox: {
    top: theme.spacing(1),
    margin: theme.spacing(0.5, 0, 1),
    padding: theme.spacing(0.5, 1),
    outline: 'none',
    border: '1px solid',
    borderColor: indigo[100],
    backgroundColor: indigo[50],
    color: indigo[900],
    borderRadius: '4px',
    fontSize: theme.typography.pxToRem(13),
  },
});

interface CodeSnippetOwnProps {
  value: string;
  html: string;
}

type CodeSnippetProps =
  CodeSnippetOwnProps &
  WithStyles<typeof styles>;

class CodeSnippet extends React.Component<CodeSnippetProps> {
  render() {
    const {value, html, classes} = this.props;
    return (
      <Box className={classes.outsideBox}>
        <Box
          className={classes.insideBox}
          dangerouslySetInnerHTML={{
            __html: html,
          }}
        />
        <NoSsr>
          <CodeCopyButton code={value} />
        </NoSsr>
      </Box>
    );
  }
}

export default connect()(withStyles(styles)(CodeSnippet));
