# Copyright 2022 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.
"""Display interactive test client.

Description
-----------
This script is used to test the DUT display functionality, just as an example.
Use XML-RPC client and ssh command to control DUT for testing.

Dependency
----------
- Use an XML-RPC client for communication.
- Use SSH to execute remote commands.

Test Procedure
--------------
Call functions defined in utils for testing
- function: function name defined in utils
- arguments: argument pass to the function
Usage::
    python3 display_interactive_client.py -i <ip> <function> <arguments>

Examples
--------
Display the specified image test.png  on the DUT::

  python3 display_interactive_client.py -i 192.168.0.1 show test

Display the specified css pattern on the DUT::

  python3 display_interactive_client.py -i 192.168.0.1 show_pattern gray

Execute a command on the DUT and return the result::

  python3 display_interactive_client.py -i 192.168.0.1 run 'ls -l'

Copy files or folders to DUT::

  python3 display_interactive_client.py -i 192.168.0.1 push \
  './test.txt /usr/local/factory/misc/'

Copy files or folders from DUT to local::

  python3 display_interactive_client.py -i 192.168.0.1 pull \
  '/usr/local/factory/misc/test.txt ./'

Extension
--------
If you want to customize your owns script, you can import
display_interactive_utils and use the following parameters.

- Initialize the test, automatically start the test item.
  comm = Communication(args.ip)
  comm.Init(TEST_ITEM)
- Set up the ssh identity file. This allows you to execute ssh without having to
  enter a password.
  comm.SetupSSHIdentity()
- Show image on the DUT, you need copy the image(PNG) file to the
  /usr/local/factory/py/test/pytests/display_interactive/static/ directory.
  comm.ShowImage(args.arguments)
- Clear test state, tear down the test environment.
  comm.tearDown()
- Run command on the DUT.
  comm.RunCommand(args.arguments)
- Push file to the DUT.
  comm.PushFile(args.arguments)
- Pull file from the DUT.
  comm.PullFile(args.arguments)
"""
import argparse
import logging

from display_interactive_utils import Communication


DEFAULT_SERVER_IP = '192.168.0.1'
TEST_ITEM = 'DisplayTest.DisplayInteractive'
function_mapping = {
    "teardown": "tearDown",
    "show": "ShowImage",
    "get_sn": "GetSerialNumber",
    "show_pattern": "ShowPattern",
    "set_display_bl": "SetDisplayBrightness",
    "set_kbbl": "SetKeyboardBacklight",
    "run": "RunCommand",
    "push": "Push",
    "pull": "Pull",
}


def main():
  """Main function."""
  parser = argparse.ArgumentParser(
      description='Display interactive test client.')
  parser.add_argument('-i', '--ip', default=DEFAULT_SERVER_IP,
                      help='IP address of the server.')
  parser.add_argument('function', choices=function_mapping.keys(),
                      help='Function to call.')
  parser.add_argument('arguments', nargs='*', default=None,
                      help='Arguments to pass to the function.')
  args = parser.parse_args()
  logging.basicConfig(level=logging.INFO, format='%(asctime)s %(message)s')
  # Initialize communication with the server/DUT.
  comm = Communication(args.ip)
  # Initialize the test and start the test automatically. If the function is
  # run, pull or push, then skip the Init.
  if args.function not in ['run', 'push', 'pull']:
    comm.Init(TEST_ITEM)
  # Setup ssh identity.
  comm.SetupSSHIdentity()
  # Call the function.
  func = function_mapping[args.function]
  arguments = '' if not args.arguments else args.arguments
  logging.info('Calling function: %s with arguments: %s', func, arguments)
  comm.__getattribute__(func)(*arguments)


if __name__ == '__main__':
  main()
