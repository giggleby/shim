# Copyright 2017 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

# pylint: disable=consider-using-f-string
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


ExtractorResultStatus = proto.FirmwareInfoExtractorResult.Status

_SERVICE_PATH = '/_ah/stubby/FactoryBundleService'


def _GenerateFailedContents(error_message):
  issue_link = ('https://issuetracker.google.com/'
                'new?component=596923&template=1242367')
  plain_content = ('If you have issues that need help, please use {}\n\n'
                   '{}').format(issue_link, error_message)
  html_content = plain_content.replace(
      issue_link, '<a href="{0}">{0}</a>'.format(issue_link))
  html_content = html_content.replace('\n', '<br>').replace(' ', '&nbsp;')
  return plain_content, html_content


class FactoryBundleService(remote.Service):
  # pylint warns no-init because it can't found the definition of parent class.

  @remote.method(proto.WorkerResult, proto.CreateBundleRpcResponse)
  def ResponseCallback(self, worker_result):
    cc_list = list(worker_result.original_request.cc_emails)

    if worker_result.status != proto.WorkerResult.Status.FAILED:
      subject = 'Bundle creation success'
      match = re.match(r'gs://{}/(.*)$'.format(config.BUNDLE_BUCKET),
                       worker_result.gs_path)
      download_link = (
          worker_result.download_link_format.format(
              urllib.quote_plus(match.group(1))) if match else '-')
      request = worker_result.original_request
      items = ['Board: {}\n'.format(request.board)]
      items.append('Device: {}\n'.format(request.project))
      items.append('Phase: {}\n'.format(request.phase))
      items.append('Toolkit Version: {}\n'.format(request.toolkit_version))
      items.append('Test Image Version: {}\n'.format(
          request.test_image_version))
      items.append('Release Image Version: {}\n'.format(
          request.release_image_version))

      if request.firmware_source:
        items.append('Firmware Source: {}\n'.format(request.firmware_source))

      items.append('\nDownload link: {}\n'.format(download_link))

      if worker_result.status == proto.WorkerResult.Status.CREATE_CL_FAILED:
        items.append('\nCannot create HWID DB CL:\n')
        items.append('{}\n'.format(worker_result.error_message))
      if request.update_hwid_db_firmware_info:
        if worker_result.cl_url:
          items.append('\nHWID CL created:\n')
          for url in worker_result.cl_url:
            items.append('<a href="{0}">{0}</a>\n'.format(url))
        else:
          items.append('\nNo HWID CL is created.\n')

      plain_content = ''.join(items)
      unprocessed_html_content = plain_content.replace(
          download_link, '<a href="{0}">{0}</a>'.format(download_link))
      html_content = unprocessed_html_content.replace('\n', '<br>').replace(
          ' ', '&nbsp;')
    else:
      subject = 'Bundle creation failed - {:%Y-%m-%d %H:%M:%S}'.format(
          datetime.datetime.now())
      plain_content, html_content = _GenerateFailedContents(
          worker_result.error_message)
      cc_list.append(config.FAILURE_EMAIL)

    kwargs = {
        'cc': cc_list,
    } if cc_list else {}
    mail.send_mail(sender=config.NOREPLY_EMAIL,
                   to=[worker_result.original_request.email], subject=subject,
                   body=plain_content, html=html_content, **kwargs)
    return proto.CreateBundleRpcResponse()

  @remote.method(proto.FirmwareInfoExtractorResult,
                 proto.ExtractFirmwareInfoRpcResponse)
  def ExtractFirmwareInfoCallback(self, extractor_result):
    mail_list = [extractor_result.original_request.email]
    if extractor_result.status == ExtractorResultStatus.NO_ERROR:
      subject = 'HWID DB Change Request Success'
      if extractor_result.cl_url:
        items = [
            'Firmware info extracted from "{}" is submitted as CL:\n'.format(
                extractor_result.original_request.image_gs_path)
        ]
        for url in extractor_result.cl_url:
          items.append('<a href="{0}">{0}</a>\n'.format(url))
        plain_content = ''.join(items)
      else:
        plain_content = ('No firmware info extracted from "{}" or the info '
                         'already exists in HWID DB. No CL is created.').format(
                             extractor_result.original_request.image_gs_path)
      html_content = plain_content.replace('\n', '<br>').replace(' ', '&nbsp;')
    else:
      mail_list.append(config.FAILURE_EMAIL)
      subject = 'Extract Firmware Info Failed - {:%Y-%m-%d %H:%M:%S}'.format(
          datetime.datetime.now())
      plain_content, html_content = _GenerateFailedContents(
          extractor_result.error_message)

    mail.send_mail(sender=config.NOREPLY_EMAIL, to=mail_list, subject=subject,
                   body=plain_content, html=html_content)

    return proto.ExtractFirmwareInfoRpcResponse()


# Map the RPC service and path
app = service.service_mappings([(_SERVICE_PATH, FactoryBundleService)])
