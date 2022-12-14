# Copyright 2022 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

from dataclasses import dataclass
import datetime
import logging
from typing import Optional

from google.cloud import storage


@dataclass
class StorageBundleMetadata:
  """A placeholder represents the metadata of a factory bundle.

  Properties:
    doc_id: The document id of the corresponding request document stored in
        Cloud Firestore.
    email: The email of the bundle creator.
    board: The board name.
    project: The project name.
    phase: The phase name.
    toolkit_version: The toolkit version.
    test_image_version: The test image version.
    release_image_version: The release image version.
    firmware_source: The firmware source, `None` if it isn't set.
  """
  doc_id: str
  email: str
  board: str
  project: str
  phase: str
  toolkit_version: str
  test_image_version: str
  release_image_version: str
  firmware_source: Optional[str] = None


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

  def UploadCreatedBundle(self, bundle_path: str,
                          bundle_metadata: StorageBundleMetadata) -> str:
    """Uploads the created bundle.

    Args:
      bundle_path: A path of the created bundle to be uploaded.
      bundle_metadata: The created bundle's metadata used to generate filename
          and set to the storage object's metadata.

    Returns:
      A string of the google storage path.
    """
    current_datetime = datetime.datetime.now()
    blob_filename = (f'factory_bundle_{bundle_metadata.project}_'
                     f'{current_datetime:%Y%m%d_%H%M}_{bundle_metadata.phase}_'
                     f'{current_datetime:%S%f}'[:-3] + '.tar.bz2')
    blob_path = (
        f'{bundle_metadata.board}/{bundle_metadata.project}/{blob_filename}')
    blob = self._bucket.blob(blob_path, chunk_size=100 * 1024 * 1024)

    # Set Content-Disposition for the correct default download filename.
    blob.content_disposition = f'filename="{blob_filename}"'
    self._logger.info('Start uploading `%s` to `%s` bucket.', bundle_path,
                      self._bucket_name)
    blob.upload_from_filename(bundle_path)

    # Set read permission for the requestor's email, the entity method creates a
    # new acl entity and add it to the blob.
    blob.acl.entity('user', bundle_metadata.email).grant_read()
    blob.acl.save()

    created_timestamp_s = blob.time_created.timestamp()
    metadata = {
        'Bundle-Creator': bundle_metadata.email,
        'Phase': bundle_metadata.phase,
        'Tookit-Version': bundle_metadata.toolkit_version,
        'Test-Image-Version': bundle_metadata.test_image_version,
        'Release-Image-Version': bundle_metadata.release_image_version,
        'User-Request-Doc-Id': bundle_metadata.doc_id,
        'Time-Created': created_timestamp_s,
    }
    if bundle_metadata.firmware_source:
      metadata['Firmware-Source'] = bundle_metadata.firmware_source
    blob.metadata = metadata
    blob.update()

    gs_path = f'gs://{self._bucket_name}/{blob_path}'
    self._logger.info('The created bundle was uploaded to `%s`.', gs_path)
    return gs_path
