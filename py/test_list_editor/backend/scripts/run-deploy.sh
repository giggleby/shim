#!/bin/bash
# Copyright 2023 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

SCRIPT_DIR="$(realpath "$(dirname "${BASH_SOURCE[0]}")")"

source "${SCRIPT_DIR}"/common.sh

check_gke_cluster_available() {
  if kubectl get no -o=json | jq '.items | length > 0' > /dev/null; then
    return 0
  else
    return 1
  fi
}

configure_gke_credentials() {
  echo "Checking credentials for connecting to GKE clusters"
  if check_gke_cluster_available; then
    echo "Verified credentials for connecting to GKE clusters."
    return 0
  else
    echo "Configuring credentials for connecting to GKE clusters."
    gcloud container clusters get-credentials test-list-editor-dev-cluster \
      --region asia-southeast1 \
      --project chromeos-factory
  fi
}

if ! gcloud_exists; then
  echo "gcloud doesn't exist, please install gcloud CLI."
fi

if ! kubectl_exists; then
  echo "kubectl doesn't exist, please install kubectl."
fi

verify_gcloud_project_set
configure_gke_credentials

DEV_IMAGE_NAME="$(gcloud secrets versions access latest\
  --secret=test_list_editor_dev_image_name)"

if [ -z "${DEV_IMAGE_NAME}" ]; then
  echo "Variables are not set! \
Please make sure variables are set before pushing the container."
  exit
fi

envsubst < scripts/dev-services.template.yaml | kubectl apply -f  -
