# Copyright 2017 The Chromium OS Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

import datetime
import json
import logging
import os
import subprocess
import textwrap
import urllib.error
import urllib.request

import google.auth
import google.auth.transport.requests
from google.cloud import storage  # pylint: disable=import-error, no-name-in-module
from google.protobuf import text_format
import yaml

from cros.factory.bundle_creator.connector import firestore_connector
from cros.factory.bundle_creator.docker import config
from cros.factory.utils import file_utils

HWID_API_SCOPE = "https://www.googleapis.com/auth/chromeoshwid"
GERRIT_URL = 'https://chrome-internal-review.googlesource.com'
GERRIT_HWID_URI = GERRIT_URL + '/c/chromeos/chromeos-hwid/+/%(clNumber)s'


class CreateBundleException(Exception):
  """An Exception raised when fail to create factory bundle."""


class HWIDAPIRequestException(Exception):
  """An Exception raised when fail to request HWID API."""


def GetAuthToken():
  """Gets the authorization token to access HWID API.

  Returns:
    A token string can be used by HTTP request.
  """
  credential, _ = google.auth.default(scopes=[HWID_API_SCOPE])
  credential.refresh(google.auth.transport.requests.Request())
  return credential.token


def CreateHWIDFirmwareInfoCL(bundle_record, original_requester):
  """Send HTTP request to HWID API to create HWID firmware info change.

  Args:
    bundle_record: A JSON string which created by finalize_bundle.
    original_requester: The email of original_requester from EasyBundleCreation.

  Returns:
    cl_url: A list contains created HWID CL url.
  """
  token = GetAuthToken()
  headers = {
      'Authorization': f'Bearer {token}',
      'Content-Type': 'application/json'
  }
  data = {
      'original_requester':
          original_requester,
      'description':
          textwrap.dedent("""\
          This CL is created by EasyBundleCreation service.

          Please DO NOT submit this to CQ manually. It will be auto merged
          without approval.
          """),
      'bundle_record':
          bundle_record
  }
  data = json.dumps(data).encode()

  url = config.HWID_API_ENDPOINT + '/v2/createHwidDbFirmwareInfoUpdateCl'
  request = urllib.request.Request(url, headers=headers, method='POST',
                                   data=data)

  logging.info('Request HTTP POST to %s', url)
  try:
    response = urllib.request.urlopen(request)
  except urllib.error.HTTPError as ex:
    error_msg = ex.read()
    try:
      error_msg = json.dumps(json.loads(error_msg), indent=2)
    except json.decoder.JSONDecodeError:
      pass
    raise HWIDAPIRequestException(error_msg)

  response = json.load(response)
  logging.info('Response: %s', response)

  cl_url = []
  if 'commits' in response:
    for commit in response['commits'].values():
      cl_url.append(GERRIT_HWID_URI % commit)

  return cl_url


def CreateBundle(create_bundle_message_proto):
  """Creates a factory bundle with the specific manifest from a user.

  If `update_hwid_db_firmware_info` is set, this function will send request to
  HWID API server to create HWID DB change for firmware info.

  Args:
    create_bundle_message_proto: A CreateBundleMessage proto message fetched
        from a Pub/Sub subscription.

  Returns:
    gs_path: A string of the google storage path.
    cl_url: A list contains created HWID CL url.
    error_msg: A string of error message when requesting HWID API failed.
  """
  logger = logging.getLogger('util.create_bundle')
  req = create_bundle_message_proto.request
  storage_client = storage.Client(project=config.GCLOUD_PROJECT)
  firestore_conn = firestore_connector.FirestoreConnector(config.GCLOUD_PROJECT)

  logger.info(text_format.MessageToString(req, as_utf8=True, as_one_line=True))

  with file_utils.TempDirectory() as temp_dir:
    os.chdir(temp_dir)
    current_datetime = datetime.datetime.now()
    bundle_name = '{:%Y%m%d}_{}'.format(current_datetime, req.phase)

    firmware_source = ('release_image/' + req.firmware_source
                       if req.HasField('firmware_source') else 'release_image')
    manifest = {
        'board': req.board,
        'project': req.project,
        # TODO(cyueh) Add 'designs' to CreateBundleRpcRequest and update UI.
        'designs': 'boxster_designs',
        'bundle_name': bundle_name,
        'toolkit': req.toolkit_version,
        'test_image': req.test_image_version,
        'release_image': req.release_image_version,
        'firmware': firmware_source,
    }
    has_firmware_setting = firestore_conn.GetHasFirmwareSettingByProject(
        req.project)
    if has_firmware_setting:
      manifest['has_firmware'] = has_firmware_setting

    with open(os.path.join(temp_dir, 'MANIFEST.yaml'), 'w') as f:
      yaml.safe_dump(manifest, f)

    cmd = [
        '/usr/local/factory/factory.par', 'finalize_bundle',
        os.path.join(temp_dir, 'MANIFEST.yaml'), '--jobs', '7'
    ]

    bundle_record_path = os.path.join(temp_dir, 'bundle_record.json')
    if req.update_hwid_db_firmware_info:
      cmd += ['--bundle-record', bundle_record_path]

    process = subprocess.Popen(cmd, bufsize=1, stdout=subprocess.PIPE,
                               stderr=subprocess.STDOUT, encoding='utf-8')
    output = ''
    while True:
      line = process.stdout.readline()
      output += line
      if line == '':
        break
      logger.info(line.strip())

    if process.wait() != 0:
      raise CreateBundleException(output)

    bundle_filename = 'factory_bundle_{}_{}.tar.bz2'.format(
        req.project, bundle_name)

    bucket = storage_client.get_bucket(config.BUNDLE_BUCKET)
    blob_filename = 'factory_bundle_{}_{:%Y%m%d_%H%M}_{}_{}.tar.bz2'.format(
        req.project, current_datetime, req.phase,
        '{:%S%f}'.format(current_datetime)[:-3])
    blob_path = '{}/{}/{}'.format(req.board, req.project, blob_filename)
    blob = bucket.blob(blob_path, chunk_size=100 * 1024 * 1024)

    # Set Content-Disposition for the correct default download filename.
    blob.content_disposition = 'filename="{}"'.format(blob_filename)
    blob.upload_from_filename(bundle_filename)

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
        'User-Request-Doc-Id': create_bundle_message_proto.doc_id,
        'Time-Created': created_timestamp_s,
    }
    if req.HasField('firmware_source'):
      metadata['Firmware-Source'] = req.firmware_source
    blob.metadata = metadata
    blob.update()
    gs_path = u'gs://{}/{}'.format(config.BUNDLE_BUCKET, blob_path)

    cl_url = []
    error_msg = None
    if req.update_hwid_db_firmware_info:
      with open(bundle_record_path, 'r') as f:
        bundle_record = f.read()
      try:
        cl_url += CreateHWIDFirmwareInfoCL(bundle_record, req.email)
      except HWIDAPIRequestException as ex:
        error_msg = str(ex)
        logging.error(error_msg)

    return gs_path, cl_url, error_msg
