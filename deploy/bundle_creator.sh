#!/bin/bash
# Copyright 2020 The Chromium OS Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

SCRIPT_DIR="$(dirname "$(readlink -f "$0")")"
FACTORY_DIR="$(readlink -f "${SCRIPT_DIR}/..")"
FACTORY_PRIVATE_DIR="${FACTORY_DIR}/../factory-private"
SOURCE_DIR="${FACTORY_DIR}/py/bundle_creator"

LOCAL_DEPLOYMENT_DIR="/tmp/bundle_creator"
LOCAL_DEPLOYMENT_VENV_DIR="${LOCAL_DEPLOYMENT_DIR}/venv"
VENV_PYTHON_NAME="python3"
LOCAL_DEPLOYMENT_VENV_PYTHON_PATH="${LOCAL_DEPLOYMENT_DIR}/venv/bin/\
${VENV_PYTHON_NAME}"
LOCAL_DEPLOYMENT_SOURCE_DIR="${LOCAL_DEPLOYMENT_DIR}/src"
LOCAL_DEPLOYMENT_BUNDLE_CREATOR_DIR="${LOCAL_DEPLOYMENT_SOURCE_DIR}/cros/\
factory/bundle_creator"
LOCAL_DEPLOYMENT_LOG_DIR="${LOCAL_DEPLOYMENT_DIR}/log"

LOCAL_BUILD_BUNDLE="${FACTORY_DIR}/build/bundle"
TOOLKIT_NAME="install_factory_toolkit.run"
LOCAL_BUILD_TOOLKIT="${LOCAL_BUILD_BUNDLE}/toolkit/${TOOLKIT_NAME}"
REMOTE_TOOLKIT_BOARD="grunt"
REMOTE_TOOLKIT_VERSION="14402.0.0"
REMOTE_TOOLKIT_PATH="gs://chromeos-releases/dev-channel/\
${REMOTE_TOOLKIT_BOARD}/${REMOTE_TOOLKIT_VERSION}/*-factory-*.zip"
CACHED_REMOTE_TOOLKIT_DIR="${LOCAL_DEPLOYMENT_DIR}/toolkit/\
${REMOTE_TOOLKIT_BOARD}/${REMOTE_TOOLKIT_VERSION}"
CACHED_REMOTE_TOOLKIT_PATH="${CACHED_REMOTE_TOOLKIT_DIR}/factory.zip"

ZONE="us-central1-a"
EMULATOR_SIDS=()

. "${FACTORY_DIR}/devtools/mk/common.sh" || exit 1
. "${FACTORY_PRIVATE_DIR}/config/bundle_creator/config.sh" || exit 1
. "${FACTORY_PRIVATE_DIR}/config/bundle_creator/send_request.sh" || exit 1

# Following variables will be assigned by `load_config <DEPLOYMENT_TYPE>`
GCLOUD_PROJECT=
DOCKER_IMAGENAME=
CONTAINER_IMAGE=
INSTANCE_TEMPLATE_NAME=
INSTANCE_GROUP_NAME=
BUNDLE_BUCKET=
PUBSUB_TOPIC=
PUBSUB_SUBSCRIPTION=
ALLOWED_LOAS_PEER_USERNAMES=
NOREPLY_EMAIL=
FAILURE_EMAIL=
APPENGINE_ID=
SERVICE_ACCOUNT=
HWID_API_ENDPOINT=

load_config_by_deployment_type() {
  local deployment_type="$1"
  if ! load_config "${deployment_type}"; then
    die "Unsupported deployment type: \"${deployment_type}\"."
  fi
}

# Prints the path of the temporary directory created by this command.
create_temp_dir() {
  info "Create a temporary directory to hold files."
  local temp_dir
  temp_dir="$(mktemp -d)"
  if [ ! -d "${temp_dir}" ]; then
    die "Failed to create a temporary placeholder for files to deploy."
  fi
  add_temp "${temp_dir}"
  echo "${temp_dir}"
}

prepare_docker_files() {
  local destiation_dir="$1"
  local env_type="$2"

  info "Prepare files for building a docker image."
  rsync -avr --exclude="app_engine*" "${SOURCE_DIR}"/* "${destiation_dir}"

  # Fill in env vars in docker/config.py
  env GCLOUD_PROJECT="${GCLOUD_PROJECT}" \
    BUNDLE_BUCKET="${BUNDLE_BUCKET}" \
    PUBSUB_SUBSCRIPTION="${PUBSUB_SUBSCRIPTION}" \
    HWID_API_ENDPOINT="${HWID_API_ENDPOINT}" \
    ENV_TYPE="${env_type}" \
    envsubst < "${SOURCE_DIR}/docker/config.py" > \
      "${destiation_dir}/docker/config.py"

  protoc -I "${SOURCE_DIR}/proto/" --python_out "${destiation_dir}/proto" \
    "${SOURCE_DIR}/proto/factorybundle.proto"
}

download_remote_toolkit() {
  mkdir -p "${CACHED_REMOTE_TOOLKIT_DIR}"
  if [ ! -f "${CACHED_REMOTE_TOOLKIT_PATH}" ]; then
    info "Download the toolkit from \`${REMOTE_TOOLKIT_PATH}\`."
    gsutil cp "${REMOTE_TOOLKIT_PATH}" "${CACHED_REMOTE_TOOLKIT_PATH}"
  else
    info "Use the cached toolkit file \`${CACHED_REMOTE_TOOLKIT_PATH}\`."
  fi
  cp "${CACHED_REMOTE_TOOLKIT_PATH}" "$1"
}

build_docker_image() {
  load_config_by_deployment_type "$1"
  local env_type="$2"
  if [ -z "${env_type}" ]; then
    env_type="$1"
  fi

  local temp_dir
  temp_dir="$(create_temp_dir)"

  prepare_docker_files "${temp_dir}" "${env_type}"
  if [ -f "${LOCAL_BUILD_TOOLKIT}" ]; then
    info "Use the local build toolkit \`${LOCAL_BUILD_TOOLKIT}\`."
    cp "${LOCAL_BUILD_TOOLKIT}" "${temp_dir}/docker"
    cp -rf "${LOCAL_BUILD_BUNDLE}/setup" "${temp_dir}/docker"
  else
    cp -f "/bin/false" "${temp_dir}/docker/${TOOLKIT_NAME}"
    download_remote_toolkit "${temp_dir}/docker/factory.zip"
    mkdir -p "${temp_dir}/docker/setup"
  fi

  info "Start building the docker image."
  docker build -t "${DOCKER_IMAGENAME}" --file "${temp_dir}/docker/Dockerfile" \
    "${temp_dir}"
}

upload_docker_image() {
  load_config_by_deployment_type "$1"

  info "Push the docker image to Container Registry."
  gcloud --project="${GCLOUD_PROJECT}" docker -- push "${DOCKER_IMAGENAME}"
  gcloud --project="${GCLOUD_PROJECT}" compute project-info \
    add-metadata --metadata bundle-creator-docker="${DOCKER_IMAGENAME}"
}

try_delete_existing_vm() {
  info "Try deleting the existing VM instance."
  local filter="zone:${ZONE} name:${INSTANCE_GROUP_NAME}"
  {
    gcloud compute instance-groups managed list --project "${GCLOUD_PROJECT}" \
      --filter="${filter}" | grep "${INSTANCE_GROUP_NAME}"
  } && {
    gcloud compute instance-groups managed delete "${INSTANCE_GROUP_NAME}" \
      --project "${GCLOUD_PROJECT}" \
      --zone "${ZONE}" \
      --quiet
  }
  return 0
}

create_vm() {
  load_config_by_deployment_type "$1"

  try_delete_existing_vm
  {
    gcloud compute instance-templates list --project="${GCLOUD_PROJECT}" \
      --filter="${INSTANCE_TEMPLATE_NAME}" | \
      grep "${INSTANCE_TEMPLATE_NAME}" && \
    info "The specific instance template ${INSTANCE_TEMPLATE_NAME} was created."
  } && {
    info "Try deleting the existing instance template."
    gcloud compute instance-templates delete --project="${GCLOUD_PROJECT}" \
      "${INSTANCE_TEMPLATE_NAME}"
  }

  info "Create a Compute Engine instance template."
  gcloud compute instance-templates --project="${GCLOUD_PROJECT}" \
    create-with-container "${INSTANCE_TEMPLATE_NAME}" \
    --machine-type=custom-8-16384 \
    --network-tier=PREMIUM --maintenance-policy=MIGRATE \
    --image=cos-stable-63-10032-71-0 --image-project=cos-cloud \
    --boot-disk-size=200GB --boot-disk-type=pd-standard \
    --boot-disk-device-name="${INSTANCE_TEMPLATE_NAME}" \
    --container-image="${CONTAINER_IMAGE}" \
    --container-restart-policy=always --container-privileged \
    --labels=container-vm=cos-stable-63-10032-71-0 \
    --service-account="${SERVICE_ACCOUNT}" \
    --scopes="https://www.googleapis.com/auth/chromeoshwid,cloud-platform"

  info "Create an instance group and start the VM instance."
  gcloud compute instance-groups managed create "${INSTANCE_GROUP_NAME}" \
    --project "${GCLOUD_PROJECT}" \
    --template "${INSTANCE_TEMPLATE_NAME}" \
    --zone "${ZONE}" \
    --size 1
}

prepare_python_venv() {
  local requirements_path="$1"
  if [ ! -d "${LOCAL_DEPLOYMENT_VENV_DIR}" ]; then
    info "Initialize a new venv \`${LOCAL_DEPLOYMENT_VENV_DIR}\`."
    virtualenv --python="${VENV_PYTHON_NAME}" "${LOCAL_DEPLOYMENT_VENV_DIR}"
  else
    info "Use the existing venv \`${LOCAL_DEPLOYMENT_VENV_DIR}\`."
  fi

  info "Install dependent python modules with \`${requirements_path}\`."
  "${LOCAL_DEPLOYMENT_VENV_PYTHON_PATH}" -m pip install -r \
      "${requirements_path}"
}

# Print the path of the test log directory created by this command, and link
# the latest directory to the new created log directory.
create_test_log_dir() {
  local test_type="$1"
  local timestamp
  timestamp="$(date +%Y%m%d_%H%M%S)"
  local log_dir
  log_dir="${LOCAL_DEPLOYMENT_LOG_DIR}/logs.test.${test_type}.${timestamp}.d"
  local log_linkpath
  log_linkpath="${LOCAL_DEPLOYMENT_LOG_DIR}/logs.test.${test_type}.latest.d"

  mkdir -p "${log_dir}"
  rm "${log_linkpath}" || true
  ln -s "$(basename "${log_dir}")" "${log_linkpath}"
  echo "${log_dir}"
}

# Print all test modules found under the specific directory.
find_test_modules() {
  local target_dir="$1"
  find_output="$(find "${target_dir}" -type f \
      -name "*_*test.py" -printf "%P\\n")"
  for path_name in ${find_output}; do
    local path_name_no_ext="${path_name%.py}"
    echo "${path_name_no_ext//\//.}"
  done
}

start_emulator() {
  local emulator_name="$1"
  local port="$2"
  {
    gcloud components list --filter="${emulator_name}"-emulator \
      2>/dev/null | grep "Not Installed" >/dev/null
  } && {
    stop_all_emulators
    die "${emulator_name}-emulator isn't installed, please run" \
      "\`sudo apt-get install google-cloud-sdk-${emulator_name}-emulator\`" \
      "before testing."
  }

  local sid
  sid="$(setsid bash -c "gcloud beta emulators ${emulator_name} start \
    --host-port=localhost:${port} \
    2>/dev/null >/dev/null & echo \$\$")"
  EMULATOR_SIDS+=("${sid}")
}

start_all_emulators() {
  info "Start all emulators."
  start_emulator "pubsub" "8080"
  eval "$(gcloud beta emulators pubsub env-init)"

  local firestore_port="8081"
  start_emulator "firestore" "${firestore_port}"
  export FIRESTORE_EMULATOR_HOST=localhost:"${firestore_port}"

  sleep 3  # Ensure the emulators are ready.
}

stop_all_emulators() {
  info "Stop all emulators."
  for sid in "${EMULATOR_SIDS[@]}"; do
    pkill -s "${sid}"
  done
}

do_deploy_appengine() {
  load_config_by_deployment_type "$1"
  local temp_dir
  temp_dir="$(create_temp_dir)"

  info "Prepare files for deploying."
  local factory_dir="${temp_dir}/cros/factory"
  local package_dir="${factory_dir}/bundle_creator"
  mkdir -p "${package_dir}"

  cp -r "${SOURCE_DIR}/app_engine" "${package_dir}"
  cp -r "${SOURCE_DIR}/connector" "${package_dir}"
  cp -r "${SOURCE_DIR}/proto" "${package_dir}"
  local allowed_array
  allowed_array=$(printf ", \'%s\'" "${ALLOWED_LOAS_PEER_USERNAMES[@]}")
  allowed_array="${allowed_array:3:$((${#allowed_array}-4))}"
  # Fill in env vars in rpc/config.py
  env GCLOUD_PROJECT="${GCLOUD_PROJECT}" \
    BUNDLE_BUCKET="${BUNDLE_BUCKET}" \
    PUBSUB_TOPIC="${PUBSUB_TOPIC}" \
    ALLOWED_LOAS_PEER_USERNAMES="${allowed_array}" \
    NOREPLY_EMAIL="${NOREPLY_EMAIL}" \
    FAILURE_EMAIL="${FAILURE_EMAIL}" \
    envsubst < "${SOURCE_DIR}/app_engine/config.py" \
    > "${package_dir}/app_engine/config.py"
  mv "${package_dir}/app_engine/app.yaml" "${temp_dir}"
  mv "${package_dir}/app_engine/requirements.txt" "${temp_dir}"

  protoc --python_out="${package_dir}/proto/" -I "${SOURCE_DIR}/proto" \
      "${SOURCE_DIR}/proto/factorybundle.proto"

  info "Start deploying the App Engine."
  gcloud --project="${GCLOUD_PROJECT}" app deploy \
    "${temp_dir}/app.yaml" --quiet
}

do_deploy_appengine_legacy() {
  load_config_by_deployment_type "$1"
  local temp_dir
  temp_dir="$(create_temp_dir)"

  info "Prepare files for deploying."
  cp -r "${SOURCE_DIR}"/app_engine_legacy/* "${temp_dir}"
  # Fill in env vars in rpc/config.py
  env BUNDLE_BUCKET="${BUNDLE_BUCKET}" \
    NOREPLY_EMAIL="${NOREPLY_EMAIL}" \
    FAILURE_EMAIL="${FAILURE_EMAIL}" \
    envsubst < "${SOURCE_DIR}/app_engine_legacy/rpc/config.py" \
    > "${temp_dir}/rpc/config.py"

  protoc -o "${temp_dir}/rpc/factorybundle.proto.def" \
    -I "${SOURCE_DIR}" "${SOURCE_DIR}/proto/factorybundle.proto"

  info "Start deploying the legacy App Engine."
  gcloud --project="${GCLOUD_PROJECT}" app deploy \
    "${temp_dir}/app.yaml" --quiet
  info "Update the Cloud Tasks queue configuration."
  gcloud --project="${GCLOUD_PROJECT}" app deploy \
    "${temp_dir}/queue.yaml" --quiet
}

do_deploy_docker() {
  build_docker_image "$1"
  upload_docker_image "$1"
  create_vm "$1"
}

do_run_docker() {
  if [[ "$1" == "prod" || "$1" == "staging" ]]; then
    die "Unsupported deployment type for \`run-docker\` command: \"$1\"."
  fi
  load_config_by_deployment_type "$1"

  # Delete the existing vm instance on the corresponding cloud project to
  # prevent processing a request twice.
  try_delete_existing_vm
  build_docker_image "$1" "local"

  # Bind the personal gcloud credentials to the docker container so that the
  # worker can use the credentials to access gcloud services.
  info "Run the docker image."
  docker run --tty --interactive --privileged \
    --volume "${HOME}/.config/gcloud:/root/.config/gcloud" \
    --env GOOGLE_CLOUD_PROJECT="${GCLOUD_PROJECT}" \
    "${CONTAINER_IMAGE}" || true
}

do_ssh_vm() {
  load_config_by_deployment_type "$1"

  vm_name=$(gcloud compute instances list --project "${GCLOUD_PROJECT}" \
    | sed -n "s/\(${INSTANCE_GROUP_NAME}-\S*\).*$/\1/p")
  gcloud --project "${GCLOUD_PROJECT}" compute ssh "${vm_name}"
}

do_request() {
  load_config_by_deployment_type "$1"

  send_request "${APPENGINE_ID}" \
    "${FACTORY_DIR}/py/bundle_creator/proto/factorybundle.proto"
}

do_test_docker() {
  rm -rf "${LOCAL_DEPLOYMENT_BUNDLE_CREATOR_DIR}"
  mkdir -p "${LOCAL_DEPLOYMENT_BUNDLE_CREATOR_DIR}"

  # Assign fake values for generating the configuration.
  GCLOUD_PROJECT="fake-gcloud-project"
  BUNDLE_BUCKET="fake-bundle-bucket"
  PUBSUB_SUBSCRIPTION="fake-sub"
  HWID_API_ENDPOINT="https://fake_hwid_api_endpoint"
  prepare_docker_files "${LOCAL_DEPLOYMENT_BUNDLE_CREATOR_DIR}" "local"
  prepare_python_venv "${SOURCE_DIR}/docker/requirements.txt"
  rsync -avr --exclude="*test\.py" "${FACTORY_DIR}/py/utils"/* \
    "${LOCAL_DEPLOYMENT_SOURCE_DIR}/cros/factory/utils"

  start_all_emulators

  local test_modules
  mapfile -t test_modules < \
      <(find_test_modules "${LOCAL_DEPLOYMENT_SOURCE_DIR}")
  info "Found ${#test_modules[@]} test modules."

  local log_dir
  log_dir="$(create_test_log_dir "docker")"
  local failed_test_modules=()
  cd "${LOCAL_DEPLOYMENT_SOURCE_DIR}" || exit
  for test_module in "${test_modules[@]}"; do
    info "Run test \`${test_module}\`."
    local logfile_path="${log_dir}/${test_module}.log"
    if ! "${LOCAL_DEPLOYMENT_VENV_PYTHON_PATH}" -m "${test_module}" \
        >"${logfile_path}" 2>&1; then
      failed_test_modules+=("${test_module}")
    fi
  done

  if [ ${#failed_test_modules[@]} -eq 0 ]; then
    info "All tests are passed!"
  else
    error "Following ${#failed_test_modules[@]} test(s) are failed:"
    for test_module in "${failed_test_modules[@]}"; do
      local logfile_path="${log_dir}/${test_module}.log"
      echo " - ${test_module}, logfile path: ${logfile_path}"
    done
  fi

  stop_all_emulators
}

print_usage() {
  cat << __EOF__
Easy Bundle Creation Service Deployment Script

commands
  $0 deploy-appengine [prod|staging|dev|dev2]
      Deploys the code and configuration under \`py/bundle_creator/app_engine\`
      to App Engine.

  $0 deploy-appengine-legacy [prod|staging|dev|dev2]
      Deploys the code and configuration under
      \`py/bundle_creator/app_engine_legacy\` to App Engine.

  $0 deploy-docker [prod|staging|dev|dev2]
      Builds a docker image from the \`py/bundle_creator/docker/Dockerfile\` and
      creates a compute engine instance which uses the docker image.

  $0 deploy-all [prod|staging|dev|dev2]
      Does \`deploy-appengine\`, \`deploy-appengine-legacy\` and
      \`deploy-docker\` commands.

  $0 run-docker [dev|dev2]
      Runs \`py/bundle_creator/docker/worker.py\` in local with the specific
      deployment type.  The worker connects to the real Cloud Project services.

  $0 ssh-vm [prod|staging|dev|dev2]
      Ssh connect to the compute engine instance.

  $0 request [prod|staging|dev|dev2]
      Sends \`CreateBundleAsync\` request to the app engine.

  $0 test-docker
      Run all tests under \`py/bundler_creator/connector\` and
      \`py/bundler_creator/docker\`.
__EOF__
}

main() {
  local subcmd="$1"
  if [ "${subcmd}" == "help" ]; then
    print_usage
  else
    case "${subcmd}" in
      deploy-appengine)
        do_deploy_appengine "$2"
        ;;
      deploy-appengine-legacy)
        do_deploy_appengine_legacy "$2"
        ;;
      deploy-docker)
        do_deploy_docker "$2"
        ;;
      deploy-all)
        do_deploy_appengine "$2"
        do_deploy_appengine_legacy "$2"
        do_deploy_docker "$2"
        ;;
      run-docker)
        do_run_docker "$2"
        ;;
      ssh-vm)
        do_ssh_vm "$2"
        ;;
      request)
        do_request "$2"
        ;;
      test-docker)
        do_test_docker
        ;;
      *)
        die "Unknown sub-command: \"${subcmd}\".  Run \`${0} help\` to print" \
            "the usage."
        ;;
    esac
  fi

  mk_success
}

main "$@"
