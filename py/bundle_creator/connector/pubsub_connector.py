# Copyright 2022 The Chromium OS Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.
#
# TODO(b/214528226): Add a unit test for this file.

from typing import Optional

from google.cloud import pubsub_v1  # pylint: disable=no-name-in-module,import-error


class PubSubConnector:
  """Connector for accessing the Pub/Sub service."""

  def __init__(self, cloud_project_id: str):
    """Initializes a Pub/Sub client by the cloud project id.

    Args:
      cloud_project_id: A cloud project id.
    """
    self._cloud_project_id = cloud_project_id
    self._subscriber_client = pubsub_v1.SubscriberClient()

  def PullFirstMessage(self, subscription_name: str) -> Optional[str]:
    """Pulls the first message from the specific Pub/Sub subscription.

    Args:
      subscription_name: The subscription name to pull a message.

    Returns:
      A string of the first message's data if it exists.  Otherwise `None` is
      returned.
    """
    subscription_path = self._subscriber_client.subscription_path(
        self._cloud_project_id, subscription_name)
    response = self._subscriber_client.pull(subscription_path, max_messages=1)
    if response and response.received_messages:
      received_message = response.received_messages[0]
      response = self._subscriber_client.acknowledge(subscription_path,
                                                     [received_message.ack_id])
      return received_message.message.data
    return None
