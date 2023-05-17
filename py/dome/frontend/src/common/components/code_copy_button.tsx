// Copyright 2023 The ChromiumOS Authors
// Use of this source code is governed by a BSD-style license that can be
// found in the LICENSE file.

import ContentCopy from '@mui/icons-material/ContentCopy';
import Button from '@mui/material/Button';
import {Theme} from '@mui/material/styles';
import {
  createStyles,
  withStyles,
  WithStyles,
} from '@mui/styles';
import clipboardCopy from 'clipboard-copy';
import React from 'react';
import {connect} from 'react-redux';

const styles = (theme: Theme) => createStyles({
  button: {
    position: 'absolute',
    top: '8px',
    right: '8px',
    textTransform: 'none',
    minWidth: '64px',
    padding: '4px 8px',
  },
  icon: {
    fontSize: theme.typography.pxToRem(13),
    marginRight: theme.spacing(0.5),
  },
});

interface CodeCopyButtonOwnProps {
  code: string;
}

type CodeCopyButtonProps =
  CodeCopyButtonOwnProps &
  WithStyles<typeof styles>;

const useClipboardCopy = () => {
  const [isCopied, setIsCopied] = React.useState(false);
  const timeout = React.useRef<ReturnType<typeof setTimeout>>();
  const mounted = React.useRef(false);

  React.useEffect(() => {
    mounted.current = true;
    return () => {
      mounted.current = false;
    };
  }, []);

  const copy = async (text: string) => {
    try {
      setIsCopied(true);
      timeout.current = setTimeout(() => {
        if (mounted) {
          setIsCopied(false);
        }
      }, 1200);
      await clipboardCopy(text);
    } catch (error) {
      // ignore error
    }
  };

  return {copy, isCopied};
};

// This component is designed to be wrapped in NoSsr
const CodeCopyButton = (props: CodeCopyButtonProps) => {
  const {code, classes} = props;
  const {copy, isCopied} = useClipboardCopy();
  return (
    <Button
      aria-label="Copy the code"
      color="primary"
      variant="contained"
      size="small"
      className={classes.button}
      onClick={async (event) => {
        event.stopPropagation();
        await copy(code);
      }}
    >
      {isCopied ? 'Copied!' :
        <><ContentCopy className={classes.icon} /> Copy</>
      }
    </Button>
  );
};

export default connect()(withStyles(styles)(CodeCopyButton));
