# Copyright 2021 The Chromium OS Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

import logging
import operator
import re

from cros.factory.hwid.service.appengine.hwid_api_helpers import bom_and_configless_helper
from cros.factory.hwid.service.appengine.hwid_api_helpers import common_helper
from cros.factory.hwid.service.appengine.hwid_api_helpers import sku_helper
from cros.factory.hwid.service.appengine.proto import hwid_api_messages_pb2  # pylint: disable=import-error, no-name-in-module


class DUTLabelHelper:

  def __init__(self, decoder_data_manager, goldeneye_memcache_adapter,
               bom_and_configless_helper_inst, sku_hepler_inst):
    self._decoder_data_manager = decoder_data_manager
    self._goldeneye_memcache_adapter = goldeneye_memcache_adapter
    self._bom_and_configless_helper = bom_and_configless_helper_inst
    self._sku_helper = sku_hepler_inst

  def GetDUTLabels(self, request):
    """Return the components of the SKU identified by the HWID."""
    hwid = request.hwid

    # If you add any labels to the list of returned labels, also add to
    # the list of possible labels.
    possible_labels = [
        'hwid_component',
        'phase',
        'sku',
        'stylus',
        'touchpad',
        'touchscreen',
        'variant',
    ]

    if not hwid:  # Return possible labels.
      return hwid_api_messages_pb2.DutLabelsResponse(
          possible_labels=possible_labels,
          status=hwid_api_messages_pb2.Status.SUCCESS)

    status, error = common_helper.FastFailKnownBadHWID(hwid)
    if status != hwid_api_messages_pb2.Status.SUCCESS:
      return hwid_api_messages_pb2.DutLabelsResponse(
          error=error, possible_labels=possible_labels, status=status)

    bc_dict = self._bom_and_configless_helper.BatchGetBOMAndConfigless(
        [hwid], verbose=True, require_vp_info=True)
    bom_configless = bc_dict.get(hwid)
    if bom_configless is None:
      return hwid_api_messages_pb2.DutLabelResponse(
          error='Internal error',
          status=hwid_api_messages_pb2.Status.SERVER_ERROR,
          possible_labels=possible_labels)
    bom = bom_configless.bom
    configless = bom_configless.configless
    status, error = bom_and_configless_helper.GetBOMAndConfiglessStatusAndError(
        bom_configless)

    if status != hwid_api_messages_pb2.Status.SUCCESS:
      return hwid_api_messages_pb2.DutLabelsResponse(
          status=status, error=error, possible_labels=possible_labels)

    try:
      sku = self._sku_helper.GetSKUFromBOM(bom, configless)
    except sku_helper.SKUDeductionError as e:
      return hwid_api_messages_pb2.DutLabelsResponse(
          status=hwid_api_messages_pb2.Status.BAD_REQUEST, error=str(e),
          possible_labels=possible_labels)

    response = hwid_api_messages_pb2.DutLabelsResponse(
        status=hwid_api_messages_pb2.Status.SUCCESS)
    response.labels.add(name='sku', value=sku['sku'])

    regexp_to_device = self._goldeneye_memcache_adapter.Get('regexp_to_device')

    if not regexp_to_device:
      # TODO(haddowk) Kick off the ingestion to ensure that the memcache is
      # up to date.
      return hwid_api_messages_pb2.DutLabelsResponse(
          error='Missing Regexp List', possible_labels=possible_labels,
          status=hwid_api_messages_pb2.Status.SERVER_ERROR)
    for (regexp, device, unused_regexp_to_project) in regexp_to_device:
      del unused_regexp_to_project  # unused
      try:
        if re.match(regexp, hwid):
          response.labels.add(name='variant', value=device)
      except re.error:
        logging.exception('invalid regex pattern: %r', regexp)
    if bom.phase:
      response.labels.add(name='phase', value=bom.phase)

    components = ['touchscreen', 'touchpad', 'stylus']
    for component in components:
      # The lab just want the existence of a component they do not care
      # what type it is.
      if configless and 'has_' + component in configless['feature_list']:
        if configless['feature_list']['has_' + component]:
          response.labels.add(name=component, value=None)
      else:
        component_value = self._sku_helper.GetComponentValueFromBOM(
            bom, component)
        if component_value and component_value[0]:
          response.labels.add(name=component, value=None)

    # cros labels in host_info store, which will be used in tast tests of
    # runtime probe
    for component in bom.GetComponents():
      if component.name and component.is_vp_related:
        name = self._decoder_data_manager.GetPrimaryIdentifier(
            bom.project, component.cls, component.name)
        name = self._decoder_data_manager.GetAVLName(component.cls, name)
        if component.information is not None:
          name = component.information.get('comp_group', name)
        response.labels.add(name="hwid_component",
                            value=component.cls + '/' + name)

    unexpected_labels = set(
        label.name for label in response.labels) - set(possible_labels)

    if unexpected_labels:
      logging.error('unexpected labels: %r', unexpected_labels)
      return hwid_api_messages_pb2.DutLabelsResponse(
          error='Possible labels are out of date',
          possible_labels=possible_labels,
          status=hwid_api_messages_pb2.Status.SERVER_ERROR)

    response.labels.sort(key=operator.attrgetter('name', 'value'))
    response.possible_labels[:] = possible_labels
    return response
