#!/bin/bash
# Copyright 2016 The Chromium OS Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

# TODO(littlecvr): functionize this file
# TODO(littlecvr): probably should be merged with setup/umpire_docker.sh

set -e

SCRIPT_DIR=$(realpath $(dirname "${BASH_SOURCE[0]}"))
HOST_DOME_DIR=$(realpath "${SCRIPT_DIR}/../py/dome")
HOST_BUILD_DIR="${HOST_DOME_DIR}/build"

DOCKER_SHARED_DIR="/docker_shared/dome"
DOCKER_UMPIRE_DIR="/docker_umpire"

DB_FILE="db.sqlite3"
BUILDER_WORKDIR="/usr/src/app"
BUILDER_OUTPUT_FILE="frontend.tar"
CONTAINER_DOME_DIR="/var/db/factory/dome"

BUILDER_DOCKERFILE="${HOST_DOME_DIR}/docker/Dockerfile.builder"
DOME_DOCKERFILE="${HOST_DOME_DIR}/docker/Dockerfile.dome"

BUILDER_IMAGE_NAME="cros/dome-builder"
DOME_IMAGE_NAME="cros/dome"

BUILDER_CONTAINER_NAME="dome_builder"
UWSGI_CONTAINER_NAME="dome_uwsgi"
NGINX_CONTAINER_NAME="dome_nginx"

DOME_PORT="8000"

do_build() {
  # build the dome builder image
  docker build \
    --file "${BUILDER_DOCKERFILE}" \
    --tag "${BUILDER_IMAGE_NAME}" \
    --build-arg workdir="${BUILDER_WORKDIR}" \
    --build-arg output_file="${BUILDER_OUTPUT_FILE}" \
    "${HOST_DOME_DIR}"

  # copy the builder's output from container to host
  mkdir -p "${HOST_BUILD_DIR}"
  docker run --name "${BUILDER_CONTAINER_NAME}" "${BUILDER_IMAGE_NAME}"
  docker cp \
    "${BUILDER_CONTAINER_NAME}:${BUILDER_WORKDIR}/${BUILDER_OUTPUT_FILE}" \
    "${HOST_BUILD_DIR}"
  docker rm "${BUILDER_CONTAINER_NAME}"

  # build the dome runner image
  # need to make sure we're using the same version of docker inside the container
  docker build \
    --file "${DOME_DOCKERFILE}" \
    --tag "${DOME_IMAGE_NAME}" \
    --build-arg dome_dir="${CONTAINER_DOME_DIR}" \
    --build-arg builder_output_file="${BUILDER_OUTPUT_FILE}" \
    --build-arg docker_version="$(docker version --format {{.Server.Version}})" \
    "${HOST_DOME_DIR}"
}

do_run() {
  # stop and remove old containers
  docker stop "${UWSGI_CONTAINER_NAME}" 2>/dev/null || true
  docker rm "${UWSGI_CONTAINER_NAME}" 2>/dev/null || true
  docker stop "${NGINX_CONTAINER_NAME}" 2>/dev/null || true
  docker rm "${NGINX_CONTAINER_NAME}" 2>/dev/null || true

  # make sure database file exists or mounting volume will fail
  if [[ ! -d "${DOCKER_SHARED_DIR}" ]]; then
    echo "Creating docker shared folder (${DOCKER_SHARED_DIR}),"
    echo "you'll be asked for root permission..."
    sudo mkdir -p "${DOCKER_SHARED_DIR}"
    sudo touch "${DOCKER_SHARED_DIR}/${DB_FILE}"
  fi

  # Migrate the database if needed (won't remove any data if the database
  # already exists, but will apply the schema changes). This command may ask
  # user questions and need the user input, so make it interactive.
  docker run \
    --rm \
    --interactive \
    --tty \
    --volume "${DOCKER_SHARED_DIR}/${DB_FILE}:${CONTAINER_DOME_DIR}/${DB_FILE}" \
    "${DOME_IMAGE_NAME}" \
    python manage.py migrate

  # start uwsgi, the bridge between django and nginx
  docker run \
    --detach \
    --restart unless-stopped \
    --name "${UWSGI_CONTAINER_NAME}" \
    --volume /var/run/docker.sock:/var/run/docker.sock \
    --volume /run \
    --volume "${DOCKER_SHARED_DIR}/${DB_FILE}:${CONTAINER_DOME_DIR}/${DB_FILE}" \
    --volume "${DOCKER_UMPIRE_DIR}:/var/db/factory/umpire" \
    "${DOME_IMAGE_NAME}" \
    uwsgi --ini uwsgi.ini

  # start nginx
  docker run \
    --detach \
    --restart unless-stopped \
    --name "${NGINX_CONTAINER_NAME}" \
    --volumes-from "${UWSGI_CONTAINER_NAME}" \
    --publish ${DOME_PORT}:80 \
    "${DOME_IMAGE_NAME}" \
    nginx -g 'daemon off;'
}

main() {
  # TODO(littlecvr): check /docker_shared
  # TODO(littlecvr): check /docker_umpire
  # TODO(littlecvr): acquire root permission if the user is not in docker group

  case "$1" in
    build)
      do_build
      ;;
    run)
      do_run
      ;;
    *)
      # TODO(littlecvr): add usage
      echo "Unrecognized command"
      ;;
  esac
}

main "$@"
