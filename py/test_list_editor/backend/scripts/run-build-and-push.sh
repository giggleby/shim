#!/bin/bash
# Copyright 2023 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

SCRIPT_DIR="$(realpath "$(dirname "${BASH_SOURCE[0]}")")"

source "${SCRIPT_DIR}"/common.sh

check_docker_credential_config() {
  echo "Checking credential helper in docker"

  docker_config_location="${HOME}/.docker/config.json"
  credential_check_cmd="$(jq -e .credHelpers.\"asia-east1-docker.pkg.dev\" \
    "${docker_config_location}")"

  if [ -e "${docker_config_location}" ] && \
    [ -n "${credential_check_cmd}" ]; then
    return 0
  else
    return 1
  fi
}

configure_gcloud_artifact_registry() {
  if check_docker_credential_config; then
    echo "Verified credential set to use asia-east1-docker.pkg.dev"
    return
  else
    echo "Set credential helper to use the correct credential helper."
    gcloud auth configure-docker asia-east1-docker.pkg.dev
  fi
}

BACKEND_IMAGE_NAME="test_list_editor_backend"

if ! gcloud_exists; then
  echo "gcloud doesn't exist, please install gcloud CLI."
fi

verify_gcloud_project_set
configure_gcloud_artifact_registry

DEV_IMAGE_NAME="$(gcloud secrets versions access latest\
  --secret=test_list_editor_dev_image_name)"

if [ -z "${DEV_IMAGE_NAME}" ]; then
  echo "Variables are not set! \
Please make sure variables are set before pushing the container."
  exit
fi

mkdir -p "${XDG_RUNTIME_DIR}"/test_list_editor
cd "${XDG_RUNTIME_DIR}"/test_list_editor || exit

rsync -avLKhz \
  --include 'cros/factory/*' \
  --exclude 'cros/factory/dome' \
  --exclude 'cros/factory/test_list_editor/frontend' \
  --exclude '*.pyc' \
  --exclude '*/__pycache__/**' \
  "${CROS_DIR}"/ .

docker build -t "${BACKEND_IMAGE_NAME}" -f \
  cros/factory/test_list_editor/backend/Dockerfile .

docker tag "${BACKEND_IMAGE_NAME}" "${DEV_IMAGE_NAME}"
docker push "${DEV_IMAGE_NAME}"
echo "Push Successfully Completed"
