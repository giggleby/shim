#!/bin/bash
# Copyright 2021 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

# shellcheck disable=SC2269
ENTITY_FILE="${ENTITY_FILE}"
# shellcheck disable=SC2269
DATASTORE_PROJECT_ID="${DATASTORE_PROJECT_ID}"
# shellcheck disable=SC2269
DATASTORE_HOST="${DATASTORE_HOST}"
# shellcheck disable=SC2269
REDIS_DB_DIR="${REDIS_DB_DIR}"

start_redis() {
  local redis_args=()
  if [ -d "${REDIS_DB_DIR}" ]; then
    redis_args+=(--dir "${REDIS_DB_DIR}")
  fi
  redis-server "${redis_args[@]}"
}

setup_integration_test() {
  start_redis &
  /usr/src/google-cloud-sdk/bin/gcloud beta emulators datastore \
    start --consistency=1 &
  bash
}

setup_local_server() {
  echo "INFO: If you need the local server able to access gerrit," \
    "please login for impersonated credential."
  read -r -p "      Run \`gcloud auth application-default login\`? [y/N]" opt
  if [[ "${opt}" =~ [yY] ]]; then
    /usr/src/google-cloud-sdk/bin/gcloud auth application-default login
  fi

  start_redis &
  /usr/src/google-cloud-sdk/bin/gcloud \
    beta emulators datastore start --consistency=1 &

  if ! /usr/src/check_datastore_status.sh; then
    echo "Datastore is not running. Abort server."
    exit 1
  fi

  if [ -f "/datastore/${ENTITY_FILE}" ]; then
    curl -X POST \
      "${DATASTORE_HOST}/v1/projects/${DATASTORE_PROJECT_ID}:import" \
      -H 'Content-Type: application/json' \
      -d "{\"input_url\": \"/datastore/${ENTITY_FILE}\"}"
  fi

  python -m flask run --host 0.0.0.0
}

start_server() {
  local deployment_type="$1"
  case "${deployment_type}" in
    "local")
      setup_local_server
      ;;
    "integration_test")
      setup_integration_test
      ;;
    *)
      echo "Invalid deployment type: ${deployment_type}"
      exit 1
      ;;
  esac
}

start_server "$1"
