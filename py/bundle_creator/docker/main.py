# Copyright 2023 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.
import logging
import time

from google.cloud import logging as gc_logging

from cros.factory.bundle_creator.docker import config
from cros.factory.bundle_creator.docker import firmware_info_extractor
from cros.factory.bundle_creator.docker import retry_failure_worker
from cros.factory.bundle_creator.docker import worker


def main():
  """The main loop tries to process a request per 30 seconds."""
  logger = logging.getLogger('main')
  create_bundle_worker = worker.EasyBundleCreationWorker()
  fw_info_extractor = firmware_info_extractor.FirmwareInfoExtractor()
  retry_failure_worker_instance = retry_failure_worker.RetryFailureWorker()
  while True:
    try:
      create_bundle_worker.TryProcessRequest()
      fw_info_extractor.TryProcessRequest()
      retry_failure_worker_instance.TryProcessRequest()
    except Exception as e:
      logger.error(e)
    time.sleep(30)


if __name__ == '__main__':
  if config.ENV_TYPE == 'local':
    logging.basicConfig(level=logging.INFO)
  else:
    gc_logging.Client().setup_logging(log_level=logging.INFO)
  main()
