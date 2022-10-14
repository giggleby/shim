# Copyright 2016 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

# This is the image for building Dome. There is another image for running Dome.
# The reason to separate them is because building requires much more
# dependencies. The dependencies are really big and we don't want to pull them
# all into the running image since they are useless after the build.

# To enter the bash of the container, run the following commands,
# 0. DOME_PATH=/path/to/platform/factory/py/dome
# 1. sudo docker build \
#      --file ${DOME_PATH}/docker/Dockerfile.builder \
#      --tag cros/dome-builder \
#      --build-arg workdir=${DOME_PATH}/frontend/ \
#      ${DOME_PATH}
# 2. sudo docker run -it --rm cros/dome-builder bash
# 3. Check environment, e.g. "npm -v" or "node -v".

FROM node:10-slim
LABEL maintainer="ChromeOS Factory Eng <chromeos-factory-eng@google.com>"

# mixing ARG and ENV to make CMD able to use the variable, this technique is
# described here: https://docs.docker.com/engine/reference/builder/#arg
ARG workdir
ENV workdir="${workdir}"

WORKDIR "${workdir}"

# copy package.json and pull in dependencies first, so we don't need to do this
# again if package.json hasn't been modified
COPY frontend/package.json frontend/package-lock.json "${workdir}"/

RUN npm install && npm dedupe

# build
COPY frontend "${workdir}/"
RUN npm run build

WORKDIR "${workdir}/build"

# make sure others can read
RUN chmod 644 app.js app.js.map main.css favicon.svg

ARG output_file="frontend.tar"
ENV output_file="${output_file}"

RUN tar cvf "${output_file}" app.js app.js.map main.css favicon.svg

# nothing to do here
CMD ["echo"]
