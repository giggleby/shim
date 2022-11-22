# Copyright 2023 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

from cros.factory.bundle_creator.app_engine_v2 import config
from cros.factory.bundle_creator.connector import firestore_connector
from cros.factory.bundle_creator.connector import pubsub_connector
from cros.factory.bundle_creator.proto import factorybundle_v2_pb2  # pylint: disable=no-name-in-module
from cros.factory.bundle_creator.utils import allowlist_utils
from cros.factory.bundle_creator.utils import protorpc_utils


class FactoryBundleServiceV2(protorpc_utils.ProtoRPCServiceBase):
  SERVICE_DESCRIPTOR = factorybundle_v2_pb2.DESCRIPTOR.services_by_name[
      'FactoryBundleServiceV2']

  _REQUEST_FROM_VALUE = 'v2'

  def __init__(self):
    self._firestore_connector = firestore_connector.FirestoreConnector(
        config.GCLOUD_PROJECT)
    self._pubsub_connector = pubsub_connector.PubSubConnector(
        config.GCLOUD_PROJECT)

  @allowlist_utils.Allowlist(config.ALLOWED_LOAS_PEER_USERNAMES)
  def CreateBundle(
      self, request: factorybundle_v2_pb2.CreateBundleRequest
  ) -> factorybundle_v2_pb2.CreateBundleResponse:
    message = factorybundle_v2_pb2.CreateBundleMessage()
    message.doc_id = self._firestore_connector.CreateUserRequest(
        firestore_connector.CreateBundleRequestInfo.FromV2CreateBundleRequest(
            request), self._REQUEST_FROM_VALUE)
    message.request.MergeFrom(request)

    attributes = {
        'request_from': self._REQUEST_FROM_VALUE,
    }
    self._pubsub_connector.PublishMessage(config.PUBSUB_TOPIC,
                                          message.SerializeToString(),
                                          attributes)

    response = factorybundle_v2_pb2.CreateBundleResponse()
    response.status = response.Status.NO_ERROR
    return response
