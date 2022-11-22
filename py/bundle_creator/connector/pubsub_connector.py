# Copyright 2022 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

from dataclasses import dataclass
from typing import Dict, Optional

from google.cloud import pubsub_v1


@dataclass
class PubSubMessage:
  """A placeholder represents a Pub/Sub message.

  Properties:
    data: A byte string of the message's data.
    attributes: A dictionary of the message's attributes.
  """
  data: bytes
  attributes: Dict[str, str]


class PubSubConnector:
  """Connector for accessing the Pub/Sub service."""

  _ORDERING_KEY = 'DEFAULT'

  def __init__(self, cloud_project_id: str):
    """Initializes a Pub/Sub client by the cloud project id.

    Args:
      cloud_project_id: A cloud project id.
    """
    self._cloud_project_id = cloud_project_id
    publisher_options = pubsub_v1.types.PublisherOptions(
        enable_message_ordering=True)
    self._publisher_client = pubsub_v1.PublisherClient(
        publisher_options=publisher_options)
    self._subscriber_client = pubsub_v1.SubscriberClient()

  def PullFirstMessage(self, subscription_name: str) -> Optional[PubSubMessage]:
    """Pulls the first message from the specific Pub/Sub subscription.

    Args:
      subscription_name: The subscription name to pull a message.

    Returns:
      A `PubSubMessage` object if a message is pulled.  Otherwise `None` is
          returned.
    """
    subscription_path = self._subscriber_client.subscription_path(
        self._cloud_project_id, subscription_name)
    response = self._subscriber_client.pull(subscription_path, max_messages=1,
                                            return_immediately=True)
    if response and response.received_messages:
      received_message = response.received_messages[0]
      response = self._subscriber_client.acknowledge(subscription_path,
                                                     [received_message.ack_id])
      return PubSubMessage(received_message.message.data,
                           received_message.message.attributes)
    return None

  def PublishMessage(self, topic_name: str, message_data: bytes,
                     attributes: Optional[Dict[str, str]] = None):
    """Publishes a message to the specific topic.

    Args:
      topic_name: The name of the topic to be published a message.
      message_data: The byte string of the data to be published.
      attributes: A dictionary of attributes to be sent as metadata.
    """
    attributes = attributes or {}
    topic_path = self._publisher_client.topic_path(self._cloud_project_id,
                                                   topic_name)
    self._publisher_client.publish(
        topic_path, message_data, ordering_key=self._ORDERING_KEY, **attributes)

  def CreateTopic(self, topic_name: str):
    """Testing purpose.  Creates a new topic.

    Args:
      topic_name: The topic name to be created.
    """
    topic_path = self._publisher_client.topic_path(self._cloud_project_id,
                                                   topic_name)
    self._publisher_client.create_topic(topic_path)

  def DeleteTopic(self, topic_name: str):
    """Testing purpose.  Deletes the specific topic.

    Args:
      topic_name: The topic name to be deleted.
    """
    topic_path = self._publisher_client.topic_path(self._cloud_project_id,
                                                   topic_name)
    self._publisher_client.delete_topic(topic_path)

  def CreateSubscription(self, topic_name: str, subscription_name: str,
                         ack_deadline_seconds: Optional[int] = None):
    """Testing purpose.  Creates a subscription.

    Args:
      topic_name: The name of the topic which the subscription belongs to.
      subscription_name: The subscription name to be created.
    """
    topic_path = self._publisher_client.topic_path(self._cloud_project_id,
                                                   topic_name)
    subscription_path = self._subscriber_client.subscription_path(
        self._cloud_project_id, subscription_name)
    self._subscriber_client.create_subscription(
        subscription_path, topic_path,
        ack_deadline_seconds=ack_deadline_seconds, enable_message_ordering=True)

  def DeleteSubscription(self, subscription_name: str):
    """Testing purpose.  Deletes the specific subscription.

    Args:
      subscription_name: The subscription name to be deleted.
    """
    subscription_path = self._subscriber_client.subscription_path(
        self._cloud_project_id, subscription_name)
    self._subscriber_client.delete_subscription(subscription_path)
