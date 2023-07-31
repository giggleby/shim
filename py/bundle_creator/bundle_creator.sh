#!/bin/bash
# Copyright 2022 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

SCRIPT_DIR="$(dirname "$(readlink -f "$0")")"
FACTORY_DIR="$(readlink -f "${SCRIPT_DIR}/../..")"
FACTORY_PRIVATE_DIR="${FACTORY_DIR}/../factory-private"
SOURCE_DIR="${FACTORY_DIR}/py/bundle_creator"

LOCAL_DEPLOYMENT_DIR="/tmp/bundle_creator"
LOCAL_DEPLOYMENT_SOURCE_DIR="${LOCAL_DEPLOYMENT_DIR}/src"
LOCAL_DEPLOYMENT_BUNDLE_CREATOR_DIR="${LOCAL_DEPLOYMENT_SOURCE_DIR}/cros/\
factory/bundle_creator"
LOCAL_DEPLOYMENT_LOG_DIR="${LOCAL_DEPLOYMENT_DIR}/log"
VENV_PYTHON_NAME="python3"
TEST_DOCKER_NAME="docker"
TEST_APPENGINE_V2_NAME="appengine_v2"

LOCAL_BUILD_BUNDLE="${FACTORY_DIR}/build/bundle"
TOOLKIT_NAME="install_factory_toolkit.run"
LOCAL_BUILD_TOOLKIT="${LOCAL_BUILD_BUNDLE}/toolkit/${TOOLKIT_NAME}"
REMOTE_TOOLKIT_BOARD="grunt"
REMOTE_TOOLKIT_VERSION="15561.0.0"
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
FW_INFO_EXTRACTOR_TOPIC=
FW_INFO_EXTRACTOR_SUBSCRIPTION=
RETRY_PUBSUB_TOPIC=
RETRY_PUBSUB_SUBSCRIPTION=
ALLOWED_LOAS_PEER_USERNAMES=
NOREPLY_EMAIL=
FAILURE_EMAIL=
RETRY_FAILURE_EMAIL=
APPENGINE_ID=
SERVICE_ACCOUNT=
HWID_API_ENDPOINT=
DOWNLOAD_LINK_FORMAT=
DOWNLOAD_LINK_FORMAT_V2=

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

prepare_proto_files() {
  local destination_dir="$1"
  protoc --python_out="${destination_dir}" -I "${SOURCE_DIR}/proto" \
      "${SOURCE_DIR}/proto/factorybundle.proto" \
      "${SOURCE_DIR}/proto/factorybundle_v2.proto"
}

prepare_docker_files() {
  local destination_dir="$1"
  local env_type="$2"

  info "Prepare files for building a docker image."
  rsync -avr --exclude="app_engine*" --exclude="utils" "${SOURCE_DIR}"/* \
      "${destination_dir}"

  # Fill in env vars in docker/config.py
  env GCLOUD_PROJECT="${GCLOUD_PROJECT}" \
    BUNDLE_BUCKET="${BUNDLE_BUCKET}" \
    PUBSUB_TOPIC="${PUBSUB_TOPIC}" \
    PUBSUB_SUBSCRIPTION="${PUBSUB_SUBSCRIPTION}" \
    FW_INFO_EXTRACTOR_SUBSCRIPTION="${FW_INFO_EXTRACTOR_SUBSCRIPTION}" \
    HWID_API_ENDPOINT="${HWID_API_ENDPOINT}" \
    ENV_TYPE="${env_type}" \
    DOWNLOAD_LINK_FORMAT="${DOWNLOAD_LINK_FORMAT}" \
    DOWNLOAD_LINK_FORMAT_V2="${DOWNLOAD_LINK_FORMAT_V2}" \
    RETRY_PUBSUB_SUBSCRIPTION="${RETRY_PUBSUB_SUBSCRIPTION}" \
    RETRY_FAILURE_EMAIL="${RETRY_FAILURE_EMAIL}" \
    envsubst < "${SOURCE_DIR}/docker/config.py" > \
      "${destination_dir}/docker/config.py"

  prepare_proto_files "${destination_dir}/proto"
}

prepare_appengine_files() {
  local destination_dir="$1"
  local version_name="$2"
  local appengine_source_name="app_engine_${version_name}"
  if [ -z "${version_name}" ]; then
    appengine_source_name="app_engine"
  fi

  local package_dir="${destination_dir}/cros/factory/bundle_creator"
  mkdir -p "${package_dir}"
  cp -r "${SOURCE_DIR}/${appengine_source_name}" "${package_dir}"
  cp -r "${SOURCE_DIR}/connector" "${package_dir}"
  cp -r "${SOURCE_DIR}/proto" "${package_dir}"
  cp -r "${SOURCE_DIR}/utils" "${package_dir}"

  local allowed_array
  allowed_array=$(printf ", \'%s\'" "${ALLOWED_LOAS_PEER_USERNAMES[@]}")
  allowed_array="${allowed_array:3:$((${#allowed_array}-4))}"
  # Fill in env vars in config.py
  env GCLOUD_PROJECT="${GCLOUD_PROJECT}" \
      BUNDLE_BUCKET="${BUNDLE_BUCKET}" \
      PUBSUB_TOPIC="${PUBSUB_TOPIC}" \
      FW_INFO_EXTRACTOR_TOPIC="${FW_INFO_EXTRACTOR_TOPIC}" \
      ALLOWED_LOAS_PEER_USERNAMES="${allowed_array}" \
      envsubst < "${SOURCE_DIR}/${appengine_source_name}/config.py" \
      > "${package_dir}/${appengine_source_name}/config.py"
  mv "${package_dir}/${appengine_source_name}/app.yaml" "${destination_dir}"
  mv "${package_dir}/${appengine_source_name}/requirements.txt" \
      "${destination_dir}"

  prepare_proto_files "${package_dir}/proto"
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

try_delete_pubsub() {
  local type="$1"
  local name="$2"
  {
    gcloud pubsub "${type}"s list --project="${GCLOUD_PROJECT}" \
      --filter="${name}" | \
      grep "${name}" && \
    info "The specific ${type} ${name} was created."
  } && {
    info "Try deleting the existing ${type}."
    gcloud pubsub "${type}"s delete "${name}" --project="${GCLOUD_PROJECT}"
  }
  return 0
}

create_pubsub() {
  local topic_name="$1"
  local subscription_name="$2"

  gcloud pubsub topics create "${topic_name}" --project="${GCLOUD_PROJECT}"
  gcloud pubsub subscriptions create "${subscription_name}" \
    --topic "${topic_name}" \
    --project="${GCLOUD_PROJECT}" \
    --expiration-period=never \
    --enable-message-ordering
}

prepare_python_venv() {
  local test_name="$1"
  local requirements_path="$2"
  local venv_dir="${LOCAL_DEPLOYMENT_DIR}/venv_${test_name}"

  if [ ! -d "${venv_dir}" ]; then
    info "Initialize a new venv \`${venv_dir}\`."
    virtualenv --python="${VENV_PYTHON_NAME}" "${venv_dir}"
  else
    info "Use the existing venv \`${venv_dir}\`."
  fi

  info "Install dependent python modules with \`${requirements_path}\`."
  "${venv_dir}/bin/${VENV_PYTHON_NAME}" -m pip install -r "${requirements_path}"
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

run_tests() {
  local test_name="$1"
  local venv_python_dir="${LOCAL_DEPLOYMENT_DIR}/venv_${test_name}"
  local venv_python_path="${venv_python_dir}/bin/${VENV_PYTHON_NAME}"

  start_all_emulators

  local test_modules
  mapfile -t test_modules < \
      <(find_test_modules "${LOCAL_DEPLOYMENT_SOURCE_DIR}")
  info "Found ${#test_modules[@]} test modules."

  local log_dir
  log_dir="$(create_test_log_dir "${test_name}")"
  local failed_test_modules=()
  cd "${LOCAL_DEPLOYMENT_SOURCE_DIR}" || exit
  for test_module in "${test_modules[@]}"; do
    info "Run test \`${test_module}\`."
    local logfile_path="${log_dir}/${test_module}.log"
    if ! "${venv_python_path}" -m "${test_module}" \
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

do_deploy_appengine() {
  load_config_by_deployment_type "$1"
  local version_name="$2"
  local description_name
  if [ -z "${version_name}" ]; then
    description_name="App Engine"
  else
    description_name="App Engine ${version_name}"
  fi

  info "Prepare files for deploying ${description_name}."
  local temp_dir
  temp_dir="$(create_temp_dir)"
  prepare_appengine_files "${temp_dir}" "${version_name}"

  info "Start deploying the ${description_name}."
  gcloud --project="${GCLOUD_PROJECT}" app deploy "${temp_dir}/app.yaml" --quiet
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

do_create_pubsub() {
  load_config_by_deployment_type "$1"

  try_delete_pubsub "subscription" "${PUBSUB_SUBSCRIPTION}"
  try_delete_pubsub "topic" "${PUBSUB_TOPIC}"
  try_delete_pubsub "subscription" "${FW_INFO_EXTRACTOR_SUBSCRIPTION}"
  try_delete_pubsub "topic" "${FW_INFO_EXTRACTOR_TOPIC}"
  try_delete_pubsub "subscription" "${RETRY_PUBSUB_SUBSCRIPTION}"
  try_delete_pubsub "topic" "${RETRY_PUBSUB_TOPIC}"

  info "Start creating Pub/Sub topic and subscription."
  create_pubsub "${PUBSUB_TOPIC}" "${PUBSUB_SUBSCRIPTION}"
  create_pubsub "${FW_INFO_EXTRACTOR_TOPIC}" \
    "${FW_INFO_EXTRACTOR_SUBSCRIPTION}"
  create_pubsub "${RETRY_PUBSUB_TOPIC}" "${RETRY_PUBSUB_SUBSCRIPTION}"
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

  local vm_name
  vm_name=$(gcloud compute instances list \
    --project "${GCLOUD_PROJECT}" \
    --zones="${ZONE}"\
    | sed -n "s/\(${INSTANCE_GROUP_NAME}-\S*\).*$/\1/p")
  gcloud --project "${GCLOUD_PROJECT}" compute ssh "${vm_name}" --zone="${ZONE}"
}

do_request() {
  load_config_by_deployment_type "$1"

  send_request "${APPENGINE_ID}" \
    "${FACTORY_DIR}/py/bundle_creator/proto/factorybundle.proto"
}

do_test_docker() {
  rm -rf "${LOCAL_DEPLOYMENT_SOURCE_DIR}"
  mkdir -p "${LOCAL_DEPLOYMENT_BUNDLE_CREATOR_DIR}"

  # Assign fake values for generating the configuration.
  GCLOUD_PROJECT="fake-gcloud-project"
  BUNDLE_BUCKET="fake-bundle-bucket"
  PUBSUB_TOPIC="fake-topic"
  PUBSUB_SUBSCRIPTION="fake-sub"
  FW_INFO_EXTRACTOR_SUBSCRIPTION="fake-fw-info-extractor-sub"
  HWID_API_ENDPOINT="https://fake_hwid_api_endpoint"
  DOWNLOAD_LINK_FORMAT="https://fake_download_link_format/?path={}"
  DOWNLOAD_LINK_FORMAT_V2="https://fake_download_link_format_v2/?path={}"
  RETRY_PUBSUB_SUBSCRIPTION="fake-retry-sub"
  RETRY_FAILURE_EMAIL="fake-retry@google.com"
  prepare_docker_files "${LOCAL_DEPLOYMENT_BUNDLE_CREATOR_DIR}" "local"
  prepare_python_venv "${TEST_DOCKER_NAME}" \
    "${SOURCE_DIR}/docker/requirements.txt"
  rsync -avr --exclude="*test\.py" "${FACTORY_DIR}/py/utils"/* \
    "${LOCAL_DEPLOYMENT_SOURCE_DIR}/cros/factory/utils"

  run_tests "${TEST_DOCKER_NAME}"
}

do_test_appengine_v2() {
  rm -rf "${LOCAL_DEPLOYMENT_SOURCE_DIR}"
  mkdir -p "${LOCAL_DEPLOYMENT_SOURCE_DIR}"

  # Assign fake values for generating the configuration.
  GCLOUD_PROJECT="fake-gcloud-project"
  ALLOWED_LOAS_PEER_USERNAMES=("foobar")
  PUBSUB_TOPIC="fake-topic"
  FW_INFO_EXTRACTOR_TOPIC="fake-fw-info-extractor-topic"
  BUNDLE_BUCKET="fake-bundle-bucket"
  prepare_appengine_files "${LOCAL_DEPLOYMENT_SOURCE_DIR}" "v2"
  prepare_python_venv "${TEST_APPENGINE_V2_NAME}" \
    "${SOURCE_DIR}/app_engine_v2/requirements.txt"

  # Remove the unit tests of unused connectors.
  local unused_connector_names=("cloudtasks" "hwid_api")
  for name in "${unused_connector_names[@]}"; do
    local filename="${name}_connector_unittest.py"
    rm -f "${LOCAL_DEPLOYMENT_BUNDLE_CREATOR_DIR}/connector/${filename}"
  done

  run_tests "${TEST_APPENGINE_V2_NAME}"
}

do_trigger_retry() {
  load_config_by_deployment_type "$1"
  local within_days="$2"
  if [[ -z "${within_days}" ]]; then
    within_days="10"
  fi

  if [[ "${within_days}" -le 0 ]]; then
    die "It's not allowed to retry failure requests within ${within_days} days."
  fi

  read -r -p \
    "Start retrying failure requests within ${within_days} days? [y/N] " \
    answer
  if [[ "${answer}" =~ ^[yY]$ ]]; then
    local requester
    requester="$(gcloud auth list --filter=status:ACTIVE \
      --format="value(account)")"
    gcloud --project="${GCLOUD_PROJECT}" pubsub topics \
      publish "${RETRY_PUBSUB_TOPIC}" --message="${within_days},${requester}" \
      >/dev/null
    info "The retry failure request is sent."
  else
    info "The retry failure request is cancelled."
  fi
}

print_usage() {
  cat << __EOF__
Easy Bundle Creation Service Deployment Script

commands
  $0 deploy-appengine [prod|staging|dev|dev2]
      Deploys the code and configuration under \`py/bundle_creator/app_engine\`
      to App Engine.

  $0 deploy-appengine-v2 [prod|staging|dev|dev2]
      Deploys the code and configuration under
      \`py/bundle_creator/app_engine_v2\` to App Engine.

  $0 deploy-appengine-legacy [prod|staging|dev|dev2]
      Deploys the code and configuration under
      \`py/bundle_creator/app_engine_legacy\` to App Engine.

  $0 deploy-docker [prod|staging|dev|dev2]
      Builds a docker image from the \`py/bundle_creator/docker/Dockerfile\` and
      creates a compute engine instance which uses the docker image.

  $0 deploy-all [prod|staging|dev|dev2]
      Does \`create-pubsub\`, \`deploy-appengine\`, \`deploy-appengine-v2\`,
      \`deploy-appengine-legacy\` and \`deploy-docker\` commands.

  $0 create-pubsub [prod|staging|dev|dev2]
      Creates Pub/Sub topic and subscription used by the appengine and docker.
      This command deletes the existing topic and subscription.

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

  $0 test-appengine-v2
      Run all tests under \`py/bundle_creator/app_engine_v2\`.

  $0 trigger-retry [prod|staging|dev|dev2] [NUMBER]
     Trigger the retry process to rerun the failed requests in \`NUMBER\` days.

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
      deploy-appengine-v2)
        do_deploy_appengine "$2" "v2"
        ;;
      deploy-appengine-legacy)
        do_deploy_appengine_legacy "$2"
        ;;
      deploy-docker)
        do_deploy_docker "$2"
        ;;
      deploy-all)
        do_create_pubsub "$2"
        do_deploy_appengine "$2"
        do_deploy_appengine "$2" "v2"
        do_deploy_appengine_legacy "$2"
        do_deploy_docker "$2"
        ;;
      create-pubsub)
        do_create_pubsub "$2"
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
      test-appengine-v2)
        do_test_appengine_v2
        ;;
      trigger-retry)
        do_trigger_retry "$2" "$3"
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
