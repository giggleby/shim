# Copyright 2023 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

FROM python:3.11-slim-buster

RUN groupadd -g 3200 appuser
RUN adduser --disabled-password --gecos '' --uid 3000 --gid 3200 appuser
USER appuser
ENV PATH="$PATH:/home/appuser/.local/bin"
ENV RUNTIME_ENV="prod"

WORKDIR /app

COPY --chown=appuser . .

RUN pip install pip-tools && \
  pip-sync cros/factory/test_list_editor/backend/requirements.txt

EXPOSE 5000

ENTRYPOINT [ "gunicorn" ]
CMD [ "-b", "0.0.0.0:5000", "cros.factory.test_list_editor.backend.main:app" ]
