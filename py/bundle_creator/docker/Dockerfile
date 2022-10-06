# Copyright 2017 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

FROM python:3.7
LABEL maintainer="Liang-Chieh Chen <jamesqaq@google.com>"

# lbzip2 is the best variant of bzip2 for `image_tool bundle`.
# zip are required by `chromeos-firmwareupdate --repack`.
RUN apt-get update && apt-get install -y \
    bzip2 \
    cgpt \
    curl \
    gcc \
    git \
    lbzip2 \
    libssl-dev \
    lsb-release \
    moreutils \
    nginx \
    pbzip2 \
    pigz \
    rsync \
    sharutils \
    sudo \
    unzip \
    vboot-utils \
    vim \
    xz-utils \
    zip

COPY docker/requirements.txt /root/
RUN pip install -r /root/requirements.txt

# Install gcloud command.
ARG gcloud_archive_name="google-cloud-sdk-363.0.0-linux-x86_64.tar.gz"
RUN cd /usr/src/ && \
  wget "https://dl.google.com/dl/cloudsdk/channels/rapid/downloads/${gcloud_archive_name}" && \
  tar xvf "${gcloud_archive_name}" && \
  google-cloud-sdk/install.sh --rc-path /root/.bashrc --quiet && \
  rm "${gcloud_archive_name}" && \
  ln -s /usr/src/google-cloud-sdk/bin/gcloud /usr/bin/gcloud && \
  ln -s /usr/src/google-cloud-sdk/bin/gsutil /usr/bin/gsutil
# The `crcmod` module is required for the `gsutil` command to download composite
# objects.
RUN pip install crcmod==1.7

COPY docker/install_factory_toolkit.run /tmp
# Use `docker/factory.zip*` here to prevent the interruption when the file
# doesn't exist.
COPY docker/factory.zip* /tmp
COPY docker/setup/ /tmp/setup
# We install toolkit, cgpt, and futility here. If `make bundle` is executed,
# then use the local bundle. Otherwise, download the bundle from gs bucket.
RUN (/tmp/install_factory_toolkit.run -- --non-cros --yes || \
     (unzip -o /tmp/factory.zip setup/cgpt setup/futility setup/libx64/* \
        toolkit/install_factory_toolkit.run -d /tmp && \
      /tmp/toolkit/install_factory_toolkit.run -- --non-cros --yes)) && \
     cd /tmp/setup && \
     cp -rf libx64 cgpt futility /usr/bin

ENV PYTHONPATH=/usr/local/factory/py_pkg

# Set user name for finalize_bundle.
ENV USER bundle_creator

COPY . /usr/local/factory/py/bundle_creator/

CMD python /usr/local/factory/py/bundle_creator/docker/worker.py
