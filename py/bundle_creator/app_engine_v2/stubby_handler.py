# Copyright 2023 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

from cros.factory.bundle_creator.app_engine_v2 import config
from cros.factory.bundle_creator.proto import factorybundle_v2_pb2  # pylint: disable=no-name-in-module
from cros.factory.bundle_creator.utils import allowlist_utils
from cros.factory.bundle_creator.utils import protorpc_utils


class FactoryBundleServiceV2(protorpc_utils.ProtoRPCServiceBase):
  SERVICE_DESCRIPTOR = factorybundle_v2_pb2.DESCRIPTOR.services_by_name[
      'FactoryBundleServiceV2']

  @allowlist_utils.Allowlist(config.ALLOWED_LOAS_PEER_USERNAMES)
  def Echo(
      self, request: factorybundle_v2_pb2.EchoRequest
  ) -> factorybundle_v2_pb2.EchoResponse:
    response = factorybundle_v2_pb2.EchoResponse()
    response.message = request.message
    return response
