# Copyright 2023 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

import datetime

from cros.factory.bundle_creator.app_engine_v2 import config
from cros.factory.bundle_creator.connector import firestore_connector
from cros.factory.bundle_creator.connector import pubsub_connector
from cros.factory.bundle_creator.connector import storage_connector
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
    self._storage_connector = storage_connector.StorageConnector(
        config.GCLOUD_PROJECT, config.BUNDLE_BUCKET)

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

  @allowlist_utils.Allowlist(config.ALLOWED_LOAS_PEER_USERNAMES)
  def GetBundleInfo(
      self, request: factorybundle_v2_pb2.GetBundleInfoRequest
  ) -> factorybundle_v2_pb2.GetBundleInfoResponse:
    response = factorybundle_v2_pb2.GetBundleInfoResponse()

    for storage_bundle_info in self._storage_connector.GetBundleInfosByProject(
        request.project):
      bundle_info = factorybundle_v2_pb2.BundleInfo()
      bundle_info.metadata.MergeFrom(
          storage_bundle_info.metadata.ToV2BundleMetadata())
      bundle_info.creator = storage_bundle_info.metadata.email
      bundle_info.status = firestore_connector.UserRequestStatus.SUCCEEDED.name
      bundle_info.blob_path = storage_bundle_info.blob_path
      bundle_info.filename = storage_bundle_info.filename
      bundle_info.bundle_created_timestamp_sec = float(
          storage_bundle_info.created_timestamp_sec)
      response.bundle_infos.append(bundle_info)

    for snapshot in self._firestore_connector.GetUserRequestsByEmail(
        request.email, request.project):
      status = snapshot.get('status', '')
      if status == firestore_connector.UserRequestStatus.SUCCEEDED.name:
        continue
      bundle_info = factorybundle_v2_pb2.BundleInfo()
      bundle_info.metadata.board = snapshot.get('board', '')
      bundle_info.metadata.project = snapshot.get('project', '')
      bundle_info.metadata.phase = snapshot.get('phase', '')
      bundle_info.metadata.toolkit_version = snapshot.get('toolkit_version', '')
      bundle_info.metadata.test_image_version = snapshot.get(
          'test_image_version', '')
      bundle_info.metadata.release_image_version = snapshot.get(
          'release_image_version', '')
      bundle_info.metadata.firmware_source = snapshot.get('firmware_source', '')
      bundle_info.creator = snapshot.get('email', '')
      bundle_info.status = status
      bundle_info.error_message = snapshot.get('error_message', '')
      # The fields with suffix `_time` are `DatetimeWithNanoseconds` objects.
      if 'request_time' in snapshot:
        bundle_info.request_time_sec = datetime.datetime.timestamp(
            snapshot.get('request_time'))
      if 'start_time' in snapshot:
        bundle_info.request_start_time_sec = datetime.datetime.timestamp(
            snapshot.get('start_time'))
      if 'end_time' in snapshot:
        bundle_info.request_end_time_sec = datetime.datetime.timestamp(
            snapshot.get('end_time'))
      response.bundle_infos.append(bundle_info)

    response.bundle_infos.sort(
        key=lambda b: b.bundle_created_timestamp_sec
        if b.status == firestore_connector.UserRequestStatus.SUCCEEDED.name else
        b.request_time_sec, reverse=True)
    return response

  @allowlist_utils.Allowlist(config.ALLOWED_LOAS_PEER_USERNAMES)
  def DownloadBundle(
      self, request: factorybundle_v2_pb2.DownloadBundleRequest
  ) -> factorybundle_v2_pb2.DownloadBundleResponse:
    response = factorybundle_v2_pb2.DownloadBundleResponse()
    self._storage_connector.GrantReadPermissionToBlob(request.email,
                                                      request.blob_path)
    response.download_link = (
        f'https://storage.cloud.google.com/{config.BUNDLE_BUCKET}/'
        f'{request.blob_path}')
    return response
