# Copyright 2022 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

from dataclasses import dataclass
from datetime import datetime
import logging
from typing import List, Optional

from google.cloud import storage


# isort: split

from cros.factory.bundle_creator.proto import factorybundle_v2_pb2  # pylint: disable=no-name-in-module


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

  def ToV2BundleMetadata(self) -> factorybundle_v2_pb2.BundleMetadata:
    metadata = factorybundle_v2_pb2.BundleMetadata()
    metadata.board = self.board
    metadata.project = self.project
    metadata.phase = self.phase
    metadata.toolkit_version = self.toolkit_version
    metadata.test_image_version = self.test_image_version
    metadata.release_image_version = self.release_image_version
    if self.firmware_source:
      metadata.firmware_source = self.firmware_source
    return metadata


@dataclass
class StorageBundleInfo:
  """A placeholder represents the information of a factory bundle.

  Properties:
    blob_path: The gs path to the factory bundle without `gs://` prefix.
    metadata: A `StorageBundleMetadata` object.
    created_timestamp_sec: A number represents the bundle created time in
        seconds.
  """
  blob_path: str
  metadata: StorageBundleMetadata
  created_timestamp_sec: float

  @property
  def filename(self):
    unused_board, unused_project, filename = self.blob_path.split('/')
    return filename


class StorageConnector:
  """Connector for accessing Cloud Storage service."""

  def __init__(self, cloud_project_id: str, bucket_name: str):
    """Initializes a Cloud Storage client by the given arguments.

    Args:
      cloud_project_id: A cloud project id.
      bucket_name: A name of the bucket which stored files.
    """
    self._logger = logging.getLogger(self.__class__.__name__)
    self._bucket_name = bucket_name
    self._bucket = storage.Client(
        project=cloud_project_id).get_bucket(bucket_name)

  def GrantReadPermissionToBlob(self, email: str, blob_path: str):
    """Grants the specific blob's read permission to the specific user.

    Args:
      email: The user's email to get the read permission.
      blob_path: The path to the blob.
    """
    blob = self._bucket.get_blob(blob_path)
    blob.acl.user(email).grant_read()
    blob.acl.save()

  def ReadFile(self, path: str):
    """Reads file from the path."""
    return self._bucket.blob(path).download_as_string()


class FactoryBundleStorageConnector(StorageConnector):
  """Connector for access Factory Bundle on Cloud Storage"""

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
    current_datetime = datetime.now()
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

  def GetBundleInfosByProject(self, project: str) -> List[StorageBundleInfo]:
    """Returns created bundles by the specific project name.

    Args:
      project: The project name used to filter.

    Returns:
      A list of `StorageBundleInfo` object.
    """
    infos = []
    for blob in self._bucket.list_blobs():
      blob_board, blob_project, unused_blob_filename = blob.name.split('/')
      if blob_project != project:
        continue
      metadata = StorageBundleMetadata(
          doc_id=blob.metadata.get('User-Request-Doc-Id', ''),
          email=blob.metadata.get('Bundle-Creator', ''),
          board=blob_board, project=blob_project, phase=blob.metadata.get(
              'Phase', ''), toolkit_version=blob.metadata.get(
                  'Tookit-Version', ''), test_image_version=blob.metadata.get(
                      'Test-Image-Version',
                      ''), release_image_version=blob.metadata.get(
                          'Release-Image-Version',
                          ''), firmware_source=blob.metadata.get(
                              'Firmware-Source', None))
      # Due to b/153287792, the blob created time `blob.time_created` isn't
      # reliable because some blobs were migrated from an old bucket.  Use
      # `Time-Created` metadata which is set in `UploadCreatedBundle` method
      # instead if it exists.
      info = StorageBundleInfo(
          blob_path=blob.name, metadata=metadata,
          created_timestamp_sec=blob.metadata.get(
              'Time-Created', datetime.timestamp(blob.time_created)))
      infos.append(info)
    return infos
