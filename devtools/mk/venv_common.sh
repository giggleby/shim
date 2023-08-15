# shellcheck disable=SC2148
# Copyright 2023 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

remove_inconsist_venv() {
  local venv_path="$1"
  if [[ -d "${venv_path}" ]]; then
    local venv_python
    venv_python="$(readlink "${venv_path}/bin/python")"
    # Migrate existing venv created without --copies. We can remove this after
    # some time.
    if [[ "${venv_python}" == "/usr/bin/python3" ]]; then
      echo "venv is not created with --copies"
      echo "removing ${venv_path}..."
      rm -rf "${venv_path}"
      return
    fi
    local local_version virtual_version
    local_version="$(python --version)"
    virtual_version="$("${venv_path}/bin/python" --version)"
    if [[ "${local_version}" != "${virtual_version}" ]]; then
      echo "venv is ${virtual_version}, target is ${local_version}"
      echo "removing ${venv_path}..."
      rm -rf "${venv_path}"
    fi
  fi
}

load_venv() {
  local venv_path="$1"
  local venv_requirements="$2"

  remove_inconsist_venv "${venv_path}"
  if ! [ -d "${venv_path}" ]; then
    echo "Cannot find '${venv_path}', install virtualvenv"
    mkdir -p "${venv_path}"
    # system-site-package: Include system site packages for packages like
    # "yaml", "mox".
    # copies: Copy the python so we can run python installed out of chroot.
    python -m venv --system-site-package --copies "${venv_path}"
  fi

  source "${venv_path}/bin/activate"

  # pip freeze --local -r REQUIREMENTS.txt outputs something like:
  #   required_package_1==A.a
  #   required_package_2==B.b
  #   ## The following requirements were added by pip freeze:
  #   added_package_1==C.c
  #   added_package_2==D.d
  #   ...
  #
  #   required_pacakge_x are packages listed in REQUIREMENTS.txt,
  #   which are packages we really care about.
  if ! diff <(pip freeze --local -r "${venv_requirements}" | \
      sed -n '/^##/,$ !p') "${venv_requirements}" ; then
    pip install --force-reinstall -r "${venv_requirements}"
  fi
}
