# Copyright 2022 The Chromium OS Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

import datetime
import logging

from google.cloud import storage  # pylint: disable=import-error, no-name-in-module

from cros.factory.bundle_creator.proto import factorybundle_pb2  # pylint: disable=no-name-in-module


class StorageConnector:
  """Connector for accessing Cloud Storage service."""

  def __init__(self, cloud_project_id: str, bucket_name: str):
    """Initializes a Cloud Storage client by the given arguments.

    Args:
      cloud_project_id: A cloud project id.
      bucket_name: A name of the bucket which stored files.
    """
    self._logger = logging.getLogger('StorageConnector')
    self._bucket_name = bucket_name
    self._bucket = storage.Client(
        project=cloud_project_id).get_bucket(bucket_name)

  def UploadCreatedBundle(
      self, bundle_path: str,
      create_bundle_message: factorybundle_pb2.CreateBundleMessage) -> str:
    """Uploads the created bundle.

    Args:
      bundle_path: A path of the created bundle to be uploaded.
      create_bundle_message: A CreateBundleMessage proto message used to
          generate metadata.

    Returns:
      A string of the google storage path.
    """
    current_datetime = datetime.datetime.now()
    req = create_bundle_message.request
    blob_filename = 'factory_bundle_{}_{:%Y%m%d_%H%M}_{}_{}.tar.bz2'.format(
        req.project, current_datetime, req.phase,
        '{:%S%f}'.format(current_datetime)[:-3])
    blob_path = '{}/{}/{}'.format(req.board, req.project, blob_filename)
    blob = self._bucket.blob(blob_path, chunk_size=100 * 1024 * 1024)

    # Set Content-Disposition for the correct default download filename.
    blob.content_disposition = 'filename="{}"'.format(blob_filename)
    self._logger.info('Start uploading `%s` to `%s` bucket.', bundle_path,
                      self._bucket_name)
    blob.upload_from_filename(bundle_path)

    # Set read permission for the requestor's email, the entity method creates a
    # new acl entity and add it to the blob.
    blob.acl.entity('user', req.email).grant_read()
    blob.acl.save()

    created_timestamp_s = blob.time_created.timestamp()
    metadata = {
        'Bundle-Creator': req.email,
        'Phase': req.phase,
        'Tookit-Version': req.toolkit_version,
        'Test-Image-Version': req.test_image_version,
        'Release-Image-Version': req.release_image_version,
        'User-Request-Doc-Id': create_bundle_message.doc_id,
        'Time-Created': created_timestamp_s,
    }
    if req.HasField('firmware_source'):
      metadata['Firmware-Source'] = req.firmware_source
    blob.metadata = metadata
    blob.update()

    gs_path = 'gs://{}/{}'.format(self._bucket_name, blob_path)
    self._logger.info('The created bundle was uploaded to `%s`.', gs_path)
    return gs_path
