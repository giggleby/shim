# Copyright 2017 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

import datetime
import re
import urllib

from google.appengine.api import mail  # pylint: disable=import-error,no-name-in-module
from protorpc import definition  # pylint: disable=import-error
from protorpc import remote  # pylint: disable=import-error
from protorpc.wsgi import service  # pylint: disable=import-error


definition.import_file_set('rpc/factorybundle.proto.def')
# The config is imported from factory-private repo.
import config  # pylint: disable=wrong-import-position

from cros.factory import proto  # pylint: disable=wrong-import-position


_SERVICE_PATH = '/_ah/stubby/FactoryBundleService'


class FactoryBundleService(remote.Service):
  # pylint warns no-init because it can't found the definition of parent class.

  @remote.method(proto.WorkerResult, proto.CreateBundleRpcResponse)
  def ResponseCallback(self, worker_result):
    mail_list = [worker_result.original_request.email]

    if worker_result.status != proto.WorkerResult.Status.FAILED:
      subject = 'Bundle creation success'
      match = re.match(r'^gs://' + config.BUNDLE_BUCKET + r'/(.*)$',
                       worker_result.gs_path)
      download_link = (
          'https://chromeos.google.com/partner/console/DownloadBundle?path='
          f'{urllib.quote_plus(match.group(1))}' if match else '-')
      request = worker_result.original_request
      items = [f'Board: {request.board}\n']
      items.append(f'Device: {request.project}\n')
      items.append(f'Phase: {request.phase}\n')
      items.append(f'Toolkit Version: {request.toolkit_version}\n')
      items.append(f'Test Image Version: {request.test_image_version}\n')
      items.append(f'Release Image Version: {request.release_image_version}\n')

      if request.firmware_source:
        items.append(f'Firmware Source: {request.firmware_source}\n')

      items.append(f'\nDownload link: {download_link}\n')

      if worker_result.status == proto.WorkerResult.Status.CREATE_CL_FAILED:
        items.append('\nCannot create HWID DB CL:\n')
        items.append(f'{worker_result.error_message}\n')
      if request.update_hwid_db_firmware_info:
        if worker_result.cl_url:
          items.append('\nHWID CL created:\n')
          for url in worker_result.cl_url:
            items.append(f'<a href="{url}">{url}</a>\n')
        else:
          items.append('\nNo HWID CL is created.\n')

      plain_content = ''.join(items)
      unprocessed_html_content = plain_content.replace(
          download_link, f'<a href="{download_link}">{download_link}</a>')
    else:
      subject = ('Bundle creation failed - '
                 f'{datetime.datetime.now():%Y-%m-%d %H:%M:%S}')
      issue_link = ('https://issuetracker.google.com/'
                    'new?component=596923&template=1242367')
      plain_content = (
          f'If you have issues that need help, please use {issue_link}\n\n'
          f'{worker_result.error_message}')
      unprocessed_html_content = plain_content.replace(
          issue_link, f'<a href="{issue_link}">{issue_link}</a>')
      mail_list.append(config.FAILURE_EMAIL)

    html_content = unprocessed_html_content.replace('\n', '<br>').replace(
        ' ', '&nbsp;')
    mail.send_mail(
        sender=config.NOREPLY_EMAIL,
        to=mail_list,
        subject=subject,
        body=plain_content,
        html=html_content)
    return proto.CreateBundleRpcResponse()


# Map the RPC service and path
app = service.service_mappings([(_SERVICE_PATH, FactoryBundleService)])
