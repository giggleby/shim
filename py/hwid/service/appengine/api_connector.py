# Copyright 2022 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

import http
import os
from typing import Mapping, Sequence
import urllib

import google.auth
from google.auth import impersonated_credentials
from google.auth.transport import requests as ga_requests

from cros.factory.hwid.service.appengine import config  # pylint: enable=import-error, no-name-in-module

CONFIG = config.CONFIG
HWID_API_SCOPE = 'https://www.googleapis.com/auth/chromeoshwid'
IMPERSONATED_SERVICE_ACCOUNT = os.getenv('IMPERSONATED_SERVICE_ACCOUNT')

# Request will be timeout if query too many AVL names at once.
AVL_NAME_BATCH_SIZE = 50


class HWIDAPIRequestError(Exception):
  """Raised when failed to query HWID API"""


def _GetAuthSession() -> ga_requests.AuthorizedSession:
  """Gets the authorization session to access HWID API."""
  credential, _ = google.auth.default(scopes=[HWID_API_SCOPE])

  # If not running on AppEngine env, use impersonated credential.
  # Require `gcloud auth application-default login`
  if IMPERSONATED_SERVICE_ACCOUNT:
    credential = impersonated_credentials.Credentials(
        source_credentials=credential,
        target_principal=IMPERSONATED_SERVICE_ACCOUNT,
        target_scopes=[HWID_API_SCOPE])

  credential.refresh(ga_requests.Request())
  return ga_requests.AuthorizedSession(credential)


class HWIDAPIConnector:

  def GetAVLNameMapping(
      self, comp_ids: Sequence[int],
      batch_size: int = AVL_NAME_BATCH_SIZE) -> Mapping[int, str]:
    """Requests HWID API to get AVL name mapping.

    Args:
      comp_ids: A list of component IDs to query.
      batch_size: Batch size of each HTTP request.

    Returns:
      A dict maps component ID to AVL name.

    Raises:
      HWIDAPIRequestError when failed to query HWID API.
    """
    session = _GetAuthSession()
    headers = {
        'Content-Type': 'application/x-www-form-urlencoded',
        'X-HTTP-Method-Override': 'GET'
    }
    url = CONFIG.hwid_api_endpoint + '/v2/avlNameMappings:batchGet'
    avl_name_mapping = {}
    for start_index in range(0, len(comp_ids), batch_size):
      batch_comp_ids = comp_ids[start_index:start_index + batch_size]
      data = urllib.parse.urlencode({'component_ids': batch_comp_ids},
                                    doseq=True)
      resp = session.post(url, headers=headers, data=data)
      if resp.status_code == http.HTTPStatus.OK:
        avl_name_mapping.update({
            int(mapping['componentId']): mapping['avlName']
            for mapping in resp.json()['avlNameMappings']
            if 'avlName' in mapping
        })
      else:
        raise HWIDAPIRequestError(
            f'Failed to query HWID API server, statuscode={resp.status_code}: '
            f'{resp.content}.')
    return avl_name_mapping
