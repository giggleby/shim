# Copyright 2022 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

from time import sleep
import unittest

from cros.factory.bundle_creator.connector import pubsub_connector


class PubSubConnectorTest(unittest.TestCase):

  _CLOUD_PROJECT_ID = 'fake-project-id'
  _TOPIC_NAME = 'fake-topic'
  _SUBSCRIPTION_NAME = 'fake-sub'
  _ACK_DEADLINE_SECONDS = 1

  @classmethod
  def setUpClass(cls):
    cls._connector = pubsub_connector.PubSubConnector(cls._CLOUD_PROJECT_ID)
    cls._connector.CreateTopic(cls._TOPIC_NAME)

  @classmethod
  def tearDownClass(cls):
    cls._connector.DeleteTopic(cls._TOPIC_NAME)

  def setUp(self):
    self._connector.CreateSubscription(
        self._TOPIC_NAME, self._SUBSCRIPTION_NAME, self._ACK_DEADLINE_SECONDS)

  def tearDown(self):
    self._connector.DeleteSubscription(self._SUBSCRIPTION_NAME)

  def testPullFirstMessage_noMessageIsPublished_returnsNone(self):
    return_value = self._connector.PullFirstMessage(self._SUBSCRIPTION_NAME)

    self.assertIsNone(return_value)

  def testPullFirstMessage_succeed_returnsExpectedData(self):
    expected_message_data = b'fake_data'
    self._connector.PublishMessage(self._TOPIC_NAME, expected_message_data)
    sleep(1)  # Ensure the message is published.

    message_data = self._connector.PullFirstMessage(self._SUBSCRIPTION_NAME)

    self.assertEqual(message_data, expected_message_data)

  def testPullFirstMessage_succeed_verifiesMessageIsAcknowledged(self):
    self._connector.PublishMessage(self._TOPIC_NAME, b'fake_data')
    sleep(1)  # Ensure the message is published.

    self._connector.PullFirstMessage(self._SUBSCRIPTION_NAME)
    # Sleep for a time longer than `ack_deadline_seconds` to ensure that if a
    # message isn't acknowledged, it can be pulled again.
    sleep(self._ACK_DEADLINE_SECONDS + 1)
    return_value = self._connector.PullFirstMessage(self._SUBSCRIPTION_NAME)

    self.assertIsNone(return_value)

  def testPullFirstMessage_multipleMessages_verifiesPullingMessagesOrder(self):
    message_data_1 = b'message_1'
    message_data_2 = b'message_2'
    message_data_3 = b'message_3'
    self._connector.PublishMessage(self._TOPIC_NAME, message_data_1)
    self._connector.PublishMessage(self._TOPIC_NAME, message_data_2)
    self._connector.PublishMessage(self._TOPIC_NAME, message_data_3)
    sleep(1)  # Ensure the messages are published.

    pulled_message_1 = self._connector.PullFirstMessage(self._SUBSCRIPTION_NAME)
    pulled_message_2 = self._connector.PullFirstMessage(self._SUBSCRIPTION_NAME)
    pulled_message_3 = self._connector.PullFirstMessage(self._SUBSCRIPTION_NAME)

    self.assertEqual(pulled_message_1, message_data_1)
    self.assertEqual(pulled_message_2, message_data_2)
    self.assertEqual(pulled_message_3, message_data_3)


if __name__ == '__main__':
  unittest.main()
