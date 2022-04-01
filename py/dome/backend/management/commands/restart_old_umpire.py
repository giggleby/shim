# Copyright 2018 The Chromium OS Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

import logging

from backend.models import Project
from django.core.management.base import BaseCommand

logger = logging.getLogger('django.%s' % __name__)


class Command(BaseCommand):
  def handle(self, *args, **kwargs):
    del args, kwargs  # Unused.
    logger.info('Restarting all old umpire containers')
    for project in Project.objects.all():
      try:
        project.TryRestartOldUmpireContainer()
      except Exception:
        logger.warning('Error when restarting umpire container %s',
                       project.name, exc_info=True)
