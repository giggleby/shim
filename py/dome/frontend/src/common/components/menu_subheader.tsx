// Copyright 2018 The Chromium OS Authors. All rights reserved.
// Use of this source code is governed by a BSD-style license that can be
// found in the LICENSE file.

import MenuItem, {MenuItemProps} from '@mui/material/MenuItem';
import {
  createStyles,
  withStyles,
  WithStyles,
} from '@mui/styles';
import {Theme} from '@mui/material/styles';
import React from 'react';

import {Omit} from '@common/types';

const styles = (theme: Theme) => createStyles({
  subtitle: {
    ...theme.typography.body1,
    color: theme.palette.grey[500],
    fontWeight: theme.typography.fontWeightMedium as any,
  },
});

type MenuSubheaderProps =
  Omit<MenuItemProps<'li', { button?: true }>, 'classes'> & WithStyles<typeof styles>;

class MenuSubheader extends React.Component<MenuSubheaderProps> {
  menuItemRef: React.RefObject<HTMLLIElement>;

  constructor(props: MenuSubheaderProps) {
    super(props);
    this.menuItemRef = React.createRef();
  }

  removeFocus() {
    const menuItemDom = this.menuItemRef.current!;
    menuItemDom.removeAttribute('tabindex');
  }

  componentDidMount() {
    this.removeFocus();
  }

  componentDidUpdate() {
    this.removeFocus();
  }

  render() {
    const {classes, ...other} = this.props;
    return (
      <MenuItem ref={this.menuItemRef} className={classes.subtitle} {...other} />
    );
  }
}

export default withStyles(styles)(MenuSubheader);
