# Copyright 2023 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

FROM node:18-alpine AS builder

COPY . /app

WORKDIR /app

RUN npm ci --omit=dev && npm run build


FROM nginx AS server

COPY --from=builder /app/build/ /usr/share/nginx/http

COPY nginx.conf /etc/nginx/conf.d/default.conf

EXPOSE 6000

CMD ["nginx", "-g", "daemon off;"]
