" Copyright 2016 The ChromiumOS Authors
" Use of this source code is governed by a BSD-style license that can be
" found in the LICENSE file.
"

if exists('g:loaded_syntastic_plugin')
  " User is using syntastic
  let pylintrc = join([g:localrc_project_root, 'devtools', 'mk', 'pylint.rc'],
      \                '/')
  let g:syntastic_python_pylint_args = '--rcfile=' . pylintrc
endif
