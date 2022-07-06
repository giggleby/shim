#!/bin/bash
# Copyright 2018 The Chromium OS Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

DEPLOY_DIR="$(dirname "$(readlink -f "$0")")"
FACTORY_DIR="$(readlink -f "${DEPLOY_DIR}/..")"
PY_PKG_DIR="${FACTORY_DIR}/py_pkg"
APPENGINE_DIR="${PY_PKG_DIR}/cros/factory/hwid/service/appengine"
HW_VERIFIER_DIR="${FACTORY_DIR}/../../platform2/hardware_verifier/proto"
RT_PROBE_DIR="${FACTORY_DIR}/../../platform2/system_api/dbus/runtime_probe"
TEST_DIR="${APPENGINE_DIR}/test"
PLATFORM_DIR="$(dirname ${FACTORY_DIR})"
REGIONS_DIR="$(readlink -f "${FACTORY_DIR}/../../platform2/regions")"
TEMP_DIR="${FACTORY_DIR}/build/hwid"
DEPLOYMENT_PROD="prod"
DEPLOYMENT_STAGING="staging"
DEPLOYMENT_LOCAL="local"
DEPLOYMENT_E2E="e2e"
DOCKER_TAG="hwid_service"
FACTORY_PRIVATE_DIR="${FACTORY_DIR}/../factory-private"
REQUEST_SCRIPT="${FACTORY_PRIVATE_DIR}/config/hwid/service/appengine/test/\
send_request.sh"
# shellcheck disable=SC2269
REDIS_RDB="${REDIS_RDB}"
# shellcheck disable=SC2269
DATASTORE="${DATASTORE}"

. "${FACTORY_DIR}/devtools/mk/common.sh" || exit 1
. "${FACTORY_PRIVATE_DIR}/config/hwid/service/appengine/config.sh" || exit 1

# Following variables will be assigned by `load_config <DEPLOYMENT_TYPE>`
GCP_PROJECT=
APP_ID=
APP_HOSTNAME=
IMPERSONATED_SERVICE_ACCOUNT=

check_docker() {
  if ! type docker >/dev/null 2>&1; then
    die "Docker not installed, abort."
  fi
  DOCKER="docker"
  if [ "$(id -un)" != "root" ]; then
    if ! echo "begin $(id -Gn) end" | grep -q " docker "; then
      echo "You are neither root nor in the docker group,"
      echo "so you'll be asked for root permission..."
      DOCKER="sudo docker"
    fi
  fi

  # Check Docker version
  local docker_version="$(${DOCKER} version --format '{{.Server.Version}}' \
                          2>/dev/null)"
  if [ -z "${docker_version}" ]; then
    # Old Docker (i.e., 1.6.2) does not support --format.
    docker_version="$(${DOCKER} version | sed -n 's/Server version: //p')"
  fi
  local error_message=""
  error_message+="Require Docker version >= ${DOCKER_VERSION} but you have "
  error_message+="${docker_version}"
  local required_version=(${DOCKER_VERSION//./ })
  local current_version=(${docker_version//./ })
  for ((i = 0; i < ${#required_version[@]}; ++i)); do
    if (( ${#current_version[@]} <= i )); then
      die "${error_message}"  # the current version array is not long enough
    elif (( ${required_version[$i]} < ${current_version[$i]} )); then
      break
    elif (( ${required_version[$i]} > ${current_version[$i]} )); then
      die "${error_message}"
    fi
  done
}

check_gcloud() {
  if ! type gcloud >/dev/null 2>&1; then
    die "Cannot find gcloud, please install gcloud first"
  fi
}

check_credentials() {
  check_gcloud

  ids="$(gcloud auth list --filter=status:ACTIVE --format="value(account)")"
  for id in ${ids}; do
    if [[ "${id}" =~ .*"@google.com" ]]; then
      return 0
    fi
  done
  project="$1"
  gcloud auth application-default --project "${project}" login
}

run_in_temp() {
  (cd "${TEMP_DIR}"; "$@")
}

prepare_cros_regions() {
  cros_regions="${TEMP_DIR}/resource/cros-regions.json"
  ${REGIONS_DIR}/regions.py --format=json --all --notes > "${cros_regions}"
  add_temp "${cros_regions}"
}

prepare_protobuf() {
  local protobuf_out="${TEMP_DIR}/protobuf_out"
  mkdir -p "${protobuf_out}"
  protoc \
    -I="${RT_PROBE_DIR}" \
    -I="${HW_VERIFIER_DIR}" \
    --python_out="${protobuf_out}" \
    "${HW_VERIFIER_DIR}/hardware_verifier.proto" \
    "${RT_PROBE_DIR}/runtime_probe.proto"

  protobuf_out="${TEMP_DIR}/cros/factory/hwid/service/appengine/proto/"
  protoc \
    -I="${TEMP_DIR}" \
    --python_out="${TEMP_DIR}" \
    "cros/factory/hwid/service/appengine/proto/hwid_api_messages.proto" \
    "cros/factory/hwid/service/appengine/proto/ingestion.proto" \
    "cros/factory/probe_info_service/app_engine/stubby.proto"
}

do_make_build_folder() {
  mkdir -p "${TEMP_DIR}"
  add_temp "${TEMP_DIR}"
  # Change symlink to hard link due to b/70037640.
  local cp_files=(cron.yaml requirements.txt .gcloudignore gunicorn.conf.py \
    start_server.sh check_datastore_status.sh)
  for file in "${cp_files[@]}"; do
    cp -l "${APPENGINE_DIR}/${file}" "${TEMP_DIR}"
  done
  cp -lr "${PY_PKG_DIR}/cros" "${TEMP_DIR}"
  if [ -d "${FACTORY_PRIVATE_DIR}" ]; then
    mkdir -p "${TEMP_DIR}/resource"
    cp -l "\
${FACTORY_PRIVATE_DIR}/config/hwid/service/appengine/configurations.yaml" \
      "${TEMP_DIR}/resource"
  fi

  prepare_protobuf
  prepare_cros_regions
}

do_deploy() {
  local deployment_type="$1"
  shift
  check_gcloud
  check_credentials "${GCP_PROJECT}"

  if [ "${deployment_type}" == "${DEPLOYMENT_PROD}" ]; then
    do_test
  fi

  do_make_build_folder

  local common_envs=(
    GCP_PROJECT="${GCP_PROJECT}"
    VPC_CONNECTOR_REGION="${VPC_CONNECTOR_REGION}"
    VPC_CONNECTOR_NAME="${VPC_CONNECTOR_NAME}"
    REDIS_HOST="${REDIS_HOST}"
    REDIS_PORT="${REDIS_PORT}"
    REDIS_CACHE_URL="${REDIS_CACHE_URL}"
    DOLLAR='$'
  )

  # Fill in env vars in app.*.yaml.template
  env "${common_envs[@]}" SERVICE=default \
    envsubst < "${APPENGINE_DIR}/app.standard.yaml.template" > \
    "${TEMP_DIR}/app.yaml"

  case "${deployment_type}" in
    "${DEPLOYMENT_LOCAL}")
      check_docker

      # Mount redis db in docker
      local redis_mount=()
      if [ -f "${REDIS_RDB}" ]; then
        redis_mount+=(--volume "${REDIS_RDB}:/dump.rdb")
      else
        echo "WARNING: redis DB not found or not provided. Will use an empty DB"
      fi

      # Mount datastore db in docker
      local datastore_mount=()
      local datastore_dir
      local entity_file
      if [ -f "${DATASTORE}" ]; then
        datastore_dir=$(dirname "${DATASTORE}")
        entity_file=$(basename "${DATASTORE}" )
        datastore_mount+=(--volume "${datastore_dir}:/datastore")
        datastore_mount+=(--env ENTITY_FILE="${entity_file}")
      else
        echo \
          "WARNING: Datastore not found or not provided. Will use an empty DB"
      fi

      # Run docker
      # NOTE: we don't need to add `/build:/build/protobuf_out` in `PYTHONPATH`
      # manually since
      # 1. `/build` will be add by `flask run`[1].
      # 2. `/build/protobuf_out` is added by
      #    `/py/hwid/service/appengine/__init__.py`
      #
      # [1]https://github.com/pallets/flask/blob/6b0c8cda/src/flask/cli.py#L191
      ${DOCKER} run --tty --interactive --publish "127.0.0.1:5000:5000" \
        "${redis_mount[@]}" "${datastore_mount[@]}" \
        --volume "${TEMP_DIR}:/build:ro" \
        --env CROS_REGIONS_DATABASE="/build/resource/cros-regions.json" \
        --env FLASK_APP="/build/cros/factory/hwid/service/appengine/app.py" \
        --env FLASK_ENV="development" \
        --env PYTHONPATH="/usr/src/lib" \
        --env IMPERSONATED_SERVICE_ACCOUNT="${IMPERSONATED_SERVICE_ACCOUNT}" \
        --env DEPLOYMENT_TYPE="local" \
        "${DOCKER_TAG}"
      ;;
    "${DEPLOYMENT_E2E}")
      run_in_temp gcloud --project="${GCP_PROJECT}" app deploy --no-promote \
        --version=e2e-test app.yaml
      ;;
    *)
      env "${common_envs[@]}" SERVICE=cron \
        envsubst < "${APPENGINE_DIR}/app.standard.yaml.template" > \
        "${TEMP_DIR}/app.cron.yaml"
      run_in_temp gcloud --project="${GCP_PROJECT}" app deploy app.yaml \
        app.cron.yaml cron.yaml
      ;;
  esac
}

do_build() {
  check_docker

  local dockerfile="${TEST_DIR}/Dockerfile"

  do_make_build_folder

  ${DOCKER} build \
    --file "${dockerfile}" \
    --tag "${DOCKER_TAG}" \
    "${TEMP_DIR}"
}

do_test() {
  # Compile proto to *_pb2.py for e2e test.
  protoc \
    -I="${PY_PKG_DIR}" \
    --python_out="${PY_PKG_DIR}" \
    "cros/factory/hwid/service/appengine/proto/hwid_api_messages.proto" \
    "cros/factory/hwid/service/appengine/proto/ingestion.proto" \
    "cros/factory/probe_info_service/app_engine/stubby.proto"
  add_temp "${PY_PKG_DIR}/cros/factory/hwid/service/appengine/proto/\
hwid_api_messages_pb2.py"
  add_temp "${PY_PKG_DIR}/cros/factory/hwid/service/appengine/proto/\
ingestion_pb2.py"
  add_temp "${PY_PKG_DIR}/cros/factory/probe_info_service/app_engine/\
stubby_pb2.py"

  # Runs all executables in the test folder.
  for test_exec in $(find "${TEST_DIR}" -executable -type f); do
    echo Running "${test_exec}"
    "${FACTORY_DIR}/bin/factory_env" "${test_exec}"
  done
}

request() {
  local deployment_type="$1"
  local proto_file="$2"
  local api="$3"

  if ! load_config "${deployment_type}" ; then
    usage
    die "Unsupported deployment type: \"${deployment_type}\"."
  fi

  "${REQUEST_SCRIPT}" "${proto_file}" "${api}" "${APP_ID}" "${APP_HOSTNAME}"
}

usage() {
  cat << __EOF__
Chrome OS HWID Service Deployment Script

commands:
  $0 help
      Shows this help message.
      More about HWIDService: go/factory-git/py/hwid/service/appengine/README.md

  $0 deploy [prod|staging]
      Deploys HWID Service to the given environment by gcloud command.

  $0 request [prod|e2e|staging] \${proto_file} \${api}
      Send request to HWID Service AppEngine. The \$proto_file should be the
      file basename in py/hwid/service/appengine/proto.
      (e.g. proto_file="hwid_api_messages")

  $0 deploy local
      Deploys HWID Service locally in a docker container. It will load the
      database from environment variables \$REDIS_RDB and \$DATASTORE. If the
      database is not provided, it will initialize an empty DB.

  $0 deploy e2e
      Deploys HWID Service to the staging server with specific version
      "e2e-test" which would not be affected with versions under development
      but just for end-to-end testing purpose.

  $0 build
      Builds docker image for AppEngine integration test or local server.

  $0 test
      Runs all executables in the test directory.

__EOF__
}

main() {
  case "$1" in
    deploy)
      shift
      [ $# -gt 0 ] || (usage && exit 1);
      local deployment_type="$1"
      shift
      if ! load_config "${deployment_type}" ; then
        usage
        die "Unsupported deployment type: \"${deployment_type}\"."
      fi
      do_deploy "${deployment_type}" "${@}"
      ;;
    build)
      shift
      do_build "${@}"
      ;;
    test)
      do_test
      ;;
    request)
      shift
      request "${@}"
      ;;
    *)
      usage
      exit 1
      ;;
  esac

  mk_success
}

main "$@"
