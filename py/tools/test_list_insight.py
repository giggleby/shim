#!/usr/bin/env python3

# Copyright 2022 The ChromiumOS Authors.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

import argparse
import copy
import json
import logging
import os.path
import re
import sys
from collections import OrderedDict

from cros.factory.test.env import paths
from cros.factory.test.test_lists import manager
from cros.factory.test.test_lists import test_list as test_list_module
from cros.factory.test.test_lists import test_list_common
from cros.factory.utils import argparse_utils
from cros.factory.utils import config_utils
from cros.factory.utils import file_utils
from cros.factory.utils import process_utils
from cros.factory.utils import sys_utils


DESCRIPTION = """
A command line tool that loads and analyzes test lists,
which will display the resolved test object and the below features:
  - which test list each attribute and argument come from.
  - overridden attributes
  - pytests removed/added from a reference list.

Each test object is a cros.factory.test.factory.FactoryTest object
with the name of 'test_list_id' + ':' + 'test_path',
e.g. main_voxel:FFT.FrontCameraQRScan
{
  "id": "FrontCameraQRScan",
  "pytest_name": "camera",
  "inherit": "FactoryTest",
  ...
  "args": {
    ...
    "num_frames_to_pass": 10,
    "QR_string": "ChromeTeam"
  },
  "locals": {
    ...
  }
}
"""

EXAMPLES = """
Example commands:

To show the test objects with "battery" in the names on
board "volteer" with project "main_voxel" in chroot,
first run `setup_board --board ${BOARD}`, then:
> test_list_insight show --board volteer main_voxel battery

To load test lists from default test list path
`/usr/local/factory/py/tests/test_list` and show the test object
"FFT.FrontCamera" with project "main_volet" on DUT:
> test_list_insight show main_volet fft.frontcamera

To show the test objects with "LED" in their names and project "main_volta"
on extracted toolkit:
> test_list_insight show --path {path_to_extracted_toolkit} main_volta LED

To show the "constants" sections and project "main_volta"
on the extracted toolkit:
> test_list_insight show --path {path_to_extracted_toolkit} main_volta constants

To compare added/removed pytests of main_voxel with generic_main
(including the pytests they inherit respectively):
> test_list_insight compare --board volteer generic_main main_voxel

* Currently, the input test object names are case-insensitive and input test list ids
  require an exact match.
"""

STYLE = {
    'BLACK': '\033[90m',
    'RED': '\033[91m',
    'GREEN': '\033[92m',
    'YELLOW': '\033[93m',
    'BLUE': '\033[94m',
    'MAGENTA': '\033[95m',
    'CYAN': '\033[96m',
    'WHITE': '\033[97m',
    'UNDERLINE': '\033[4m',
    'SELECTED': '\33[7m',
    'RESET': '\033[0m'
}

TEST_LIST_DIR = '/usr/local/factory/py/test/test_lists'


def CreateParser():
  parser = argparse.ArgumentParser(
      prog='test_list_insight',
      formatter_class=argparse.RawDescriptionHelpFormatter,
      description=DESCRIPTION, epilog=EXAMPLES)
  subparsers = parser.add_subparsers(
      dest='subcommand',
      help='show which test list each attribute and argument come from; '
      'compare pytests of two test lists')
  subparsers.required = True

  # Create the parser for the "show" argument command.
  parser_show_argument = subparsers.add_parser('show', help='test_list target')
  # Positional arguments.
  parser_show_argument.add_argument(
      'testlist', type=str, help='a test list with "tests" defined'
      'Only test list which defines "tests" can be loaded.')
  parser_show_argument.add_argument(
      'target', type=str,
      help='a factory object\'s name/path, or "constants", "options"')

  # Create the parser for the "compare" pytest command.
  parser_compare_pytest = subparsers.add_parser('compare',
                                                help='test_list_a test_list_b')
  # Positional arguments.
  parser_compare_pytest.add_argument(
      'testlist_a', type=str, help='a test list with "tests" defined'
      'Only test list which defines "tests" can be loaded.')
  parser_compare_pytest.add_argument(
      'testlist_b', type=str, help='the second test list with "tests" defined'
      'Only test list which defines "tests" can be loaded.')

  # Optional arguments for all subparsers.
  group = parser.add_mutually_exclusive_group(required=False)
  group.add_argument('--board', type=str,
                     help='current board name; the flag is only used in Chroot')
  group.add_argument(
      '--path',
      type=str,
      action='store',
      help='path to the dir where toolkit is extracted',
  )

  parser.add_argument(
      '-v', '--verbose', type=str, action=argparse_utils.VerbosityAction,
      default=logging.WARNING, choices='01234', dest='verbose',
      help='Display process for resolving test objects'
      ' or extra error message'
      '\n* 4: logging.DEBUG'
      '\n* 3: logging.INFO'
      '\n* 2: logging.WARNING (default)'
      '\n* 1: logging.ERROR'
      '\n* 0: logging.CRITICAL')

  return parser


def Colorize(_string, extra_str='', color='CYAN'):
  return STYLE[color] + str(_string) + str(extra_str) + STYLE['RESET']


# pylint: disable=protected-access
class TestListInsightConfigList(config_utils._ConfigList):
  """Structure to store a list of raw configs"""

  def _RemoveTestListConfigSuffix(self, test_list):
    return test_list.split('.')[0]

  def AddSourceToTestList(self, resolved_test_list):
    """Compare the resolved config with raw configs to find sources.

    After config_utils._ConfigList.Resolve(), we compare the resolved test list
    with the raw configs in the reversed order.
    The result annotation is stored in resolved_test_list.

    Args:
      resolved_test_list: a resolved config.
    """
    # TestListInsightConfigList is an OrderedDict, which records
    # the test list config name and its config.
    # The keys are added from the highest level (e.g. main_xxx.test_list)
    # to the lowest level test list. (e.g. base.test_list)
    for key in reversed(self):  # pylint: disable=bad-reversed-sequence
      for unused_config_dir, config in reversed(self[key]):
        # copy to avoid changing the order when looping dictionaries.
        copy_config = copy.deepcopy(config)
        test_list_id = self._RemoveTestListConfigSuffix(key)
        test_list_def = copy_config.get('definitions', {})
        for test_object_name in resolved_test_list['definitions']:
          self._AddSourceToTestObject(
              resolved_test_list['definitions'][test_object_name],
              test_list_def.get(test_object_name, {}),
              '%s; %s' % (test_list_id, test_object_name))
        for _key in ['constants', 'options']:
          if _key in config:
            self._AddSourceToDict(resolved_test_list[_key], config[_key],
                                  '%s; %s' % (test_list_id, _key))

  def _AddSourceToDict(self, to_be_resolved_object, source_object, source_name):
    """An internal function to add sources for arguments inside a dictionary.

    Args:
      to_be_resolved_object: an object that needs source tag.
      source_object: an object from source.
      source_name: the name of source.

    Example cases:
      {
        "pytest_name": "tablet_rotation",
        "args": {
          "degrees_to_orientations": {
            "lid": {
              "0":{
                "in_accel_x": 0}}},
          "spec_offset": [1.5, 1.5]}}
    """
    if not isinstance(to_be_resolved_object, dict):
      return
    for arg_key in source_object:
      if arg_key in to_be_resolved_object:
        self._AddSourceToDict(to_be_resolved_object[arg_key],
                              source_object[arg_key], source_name)
        # Record the source test list id of the argument.
        od = OrderedDict()  # store the order of loaded sources.
        # Add prefix '__comment' to avoid error from validating test list.
        tagged_arg_key = '%s_%s' % ('__comment', Colorize(arg_key, '__source'))
        to_be_resolved_object.setdefault(tagged_arg_key, od)
        to_be_resolved_object[tagged_arg_key][source_name] = source_object[
            arg_key]

  def _AddSourceToTestObject(self, to_be_resolved_object, source_object,
                             source_name):
    """Store the fully resolved test list with sources of each argument.

    Recursively update to_be_resolved_object for "subtests" and "args"
    within "definitions".

    Args:
      to_be_resolved_object: an object needs source tag.
      source_object: an object from source.
      source_name: the name of source.
    """

    if len(source_object) == 0:  # an empty {}
      return
    # Recursively traverse test object.
    # to_be_resolved_object is a single object
    if isinstance(to_be_resolved_object, str):
      # Return when it's an object name.
      return

    if 'subtests' in to_be_resolved_object and 'subtests' in source_object:
      source_subtests = source_object['subtests']
      for to_be_resolved_sub_object in to_be_resolved_object['subtests']:
        try:
          source_sub_object = source_subtests[source_subtests.index(
              to_be_resolved_sub_object)]
          self._AddSourceToTestObject(to_be_resolved_sub_object,
                                      source_sub_object, source_name)
        except ValueError:  # index() fails -> subtest is not in the test object
          pass
    # After recursing, find where does each item in 'args' defined.
    if 'args' in to_be_resolved_object and 'args' in source_object:
      self._AddSourceToDict(to_be_resolved_object['args'],
                            source_object['args'], source_name)

# pylint: disable=protected-access
config_utils._ConfigList = TestListInsightConfigList


class TestListInsightManager(manager.Manager):
  """An extended manager to initialize the functions."""

  def _UpdateLayout(self, test_object, copy_object):
    """Remove prefix "__comment_" from keys in dict."""

    for arg_key, arg_val in copy_object.items():
      if isinstance(arg_val, dict):
        try:
          self._UpdateLayout(test_object[arg_key], arg_val)
        except KeyError:
          logging.debug('The key is already modified.')
      elif arg_key == 'subtests':
        for obj_, copy_ in zip(test_object['subtests'], arg_val):
          if isinstance(obj_, dict):
            self._UpdateLayout(obj_, copy_)
      if '__comment_' in str(arg_key):
        test_object[arg_key.replace('__comment_',
                                    '')] = test_object.pop(arg_key)

  def FindTarget(self, target, target_list_id):
    """Find the arguments given a test object path (target).

    Args:
      target: the name of the test object to be found.
      target_list_id: a test list id with "tests" defined.

    Returns:
      Argument lists of the target test object.
    """

    # Get two dicts in which key is the test_list name (e.g. generic_main),
    # and the value is a TestList object.
    raw_config = self.loader.Load(target_list_id, allow_inherit=True)

    # Get the resolved_test_list, which indicates the sources of all arguments
    # after completing test list level inheritance.
    config_dirs = [self.loader.config_dir]
    config_name = test_list_common.GetTestListConfigName(target_list_id)
    current_frame = sys._getframe(1)  # pylint: disable=protected-access
    # pylint: disable=protected-access
    config_name, config_dirs = config_utils._ResolveConfigInfo(
        config_name, current_frame, config_dirs)

    logger = config_utils._GetLogger()  # pylint: disable=protected-access
    # pylint: disable=protected-access
    raw_config_list = config_utils._LoadRawConfigList(config_name, config_dirs,
                                                      True, logger, {})
    resolved_test_list = raw_config_list.Resolve()
    # add source tags to resolved_test_list
    raw_config_list.AddSourceToTestList(resolved_test_list)

    # resolved_test_list provides an overview of the result after test list
    # level inheritance.
    logging.debug(
        json.dumps(resolved_test_list,
                   indent=2).encode('utf-8').decode('unicode_escape'))
    # Though test_list.schema allow key started with "__comment" in options,
    # TestList didn't filter these special keys properly.
    # Thus we cannot update "options"
    for _key in ['constants', 'definitions']:
      raw_config[_key].update(resolved_test_list[_key])
    # Convert raw_config (TestListConfig) to a TestList object.
    update_test_list = test_list_module.TestList(raw_config, self.checker,
                                                 self.loader)
    # Convert update_test_list to a factory_test_list
    # and complete object level inheritance.
    try:
      update_test_list.ToFactoryTestList()
    except KeyError:
      print('Only test list which defines "tests" can be loaded. '
            '%s does not have "tests"' % target_list_id)
      raise

    json_constants = dict(update_test_list.constants)
    self._UpdateLayout(json_constants, copy.deepcopy(json_constants))
    self._UpdateLayout(resolved_test_list['options'],
                       copy.deepcopy(resolved_test_list['options']))
    factory_objects = {}
    if target == 'options':
      factory_objects['options'] = json.dumps(
          resolved_test_list['options'],
          indent=2).encode('utf-8').decode('unicode_escape')
    if target == 'constants':
      factory_objects['constants'] = json.dumps(
          json_constants, indent=2).encode('utf-8').decode('unicode_escape')
    # The keys of update_test_list are test_list_id + test_path,
    # e.g. main_volteer:FAT.FrontCamera.
    for object_name in update_test_list.path_map:
      if target.casefold() in object_name.casefold():
        factory_object = update_test_list.path_map[object_name].ToStruct()
        # update keys in json: strip "_comment"
        self._UpdateLayout(factory_object, copy.deepcopy(factory_object))
        factory_objects[object_name] = json.dumps(
            factory_object,
            indent=4,
        ).encode('utf-8').decode('unicode_escape')

    return factory_objects

  def _LoadTestList(self, ref_id, tar_id):
    valid_test_list, failed_test_lists = self.BuildAllTestLists()
    # Get two dicts in which key is the test_list name (e.g. generic_main),
    # and the value is a TestList object.
    if len(failed_test_lists) > 0:
      logging.warning('These test lists cannot be loaded:')
      logging.warning(failed_test_lists)
    if len(valid_test_list) == 0:
      logging.warning('No available test lists in the directory: %s',
                      self.loader.config_dir)

    ref_test_list = valid_test_list[ref_id]
    tar_test_list = valid_test_list[tar_id]
    return ref_test_list, tar_test_list

  def CollectPytests(self, factory_test_list):
    """Find the pytests given a resolved test list.

    Group the pytests according to their each test groups, e.g. SMT, GRT.

    Args:
      factory_test_list: a dictionary of factory test objects.

    Returns:
      pytest_dict: a dictionary with keys equal to the group names
        and values corresponding to their pytests in sets.
    """

    pytest_dict = {}
    _FIRST_GROUP_NAME_REGEX = r':(.*?)\.'
    for k, v in factory_test_list.path_map.items():
      pytest = v.ToStruct()['pytest_name']
      if pytest is None:
        continue
      # the key of the path_map object looks like
      # main_xxx:SMT.ModelSKU.BoxsterModelAndSKU
      # and we extract the first test group name.
      result = re.search(_FIRST_GROUP_NAME_REGEX, k)
      if result is None:
        continue
      first_group_name = result.group(1)
      colorized_group_name = Colorize(first_group_name, color='YELLOW')
      pytest_dict.setdefault(colorized_group_name, set())
      pytest_dict[colorized_group_name].add(pytest)

    return pytest_dict

  def ComparePytests(self, ref_id, tar_id):
    """Get pytests from two test lists and compare the difference.

    Args:
      ref_id: ID of the reference test list.
      tar_id: ID of the target test list.

    Output:
      Two lists of added pytests and removed pytests respectively.
    """

    try:
      ref_test_list, tar_test_list = self._LoadTestList(ref_id, tar_id)
    except KeyError as e:
      print('Only test list which defines "tests" can be loaded. '
            '%s is not in the directory or does not have "tests"' % e)
      return
    ref_py_dict = self.CollectPytests(ref_test_list)
    tar_py_dict = self.CollectPytests(tar_test_list)
    print('\nRed: pytests removed from %s\n'
          'Green: pytests added in %s\n' % (tar_id, tar_id))
    for test_group, tar_pytest_list in tar_py_dict.items():
      ref_pytest_list = ref_py_dict[test_group]
      added = tar_pytest_list - ref_pytest_list
      removed = ref_pytest_list - tar_pytest_list
      print(test_group)
      for x in removed:
        ref_pytest_list.remove(x)
        ref_pytest_list.add(Colorize(x, color='RED'))
      for x in added:
        tar_pytest_list.remove(x)
        tar_pytest_list.add(Colorize(x, color='GREEN'))

      print(Colorize(tar_id, color='RED'))
      print(
          json.dumps(sorted(
              list(ref_pytest_list))).encode('utf-8').decode('unicode_escape'))
      print(Colorize(ref_id, color='GREEN'))
      print(
          json.dumps(sorted(
              list(tar_pytest_list))).encode('utf-8').decode('unicode_escape'))


def main(args):
  # Set up logging format.
  root = logging.getLogger()
  root.setLevel(logging.DEBUG)
  parser = CreateParser()
  options = parser.parse_args()

  handler = logging.StreamHandler(sys.stdout)
  handler.setLevel(options.verbose)
  formatter = logging.Formatter('%(levelname)s - %(message)s',
                                '%Y/%m/%d %H:%M:%S')
  handler.setFormatter(formatter)
  root.addHandler(handler)

  insight_manager = TestListInsightManager()

  if options.board:
    if not sys_utils.InChroot():
      raise ValueError('`board` argument is only availabe in chroot')

    process_utils.Spawn(['make', 'overlay-' + options.board],
                        cwd=paths.FACTORY_DIR, check_call=True,
                        ignore_stdout=True)
    # Run the copy of this script under overlay-board directory.
    overlay_dir = os.path.join(paths.FACTORY_DIR, 'overlay-' + options.board)
    overlay_factory_env = os.path.join(overlay_dir, 'bin', 'factory_env')
    tools_dir = os.path.join(overlay_dir, 'py', 'tools')
    overlay_checker_path = os.path.join(tools_dir, os.path.basename(__file__))
    # Remove --board argument to avoid error in CheckCall() and Spawn().
    board_index = args.index('--board')
    new_args = ([overlay_factory_env, overlay_checker_path] +
                args[:board_index] + args[board_index + 2:])
    try:
      process_utils.CheckCall(new_args)
      return
    except process_utils.CalledProcessError:
      logging.exception('Search failed.')

  elif options.path:
    try:
      file_utils.CheckPath(options.path)
    except IOError:
      logging.critical('Directory is not found. \n %s', options.path)
      return

    # Default path is 'factory/py/test/test_lists' defined in test_list_common.
    # Recommend to decompress the factory toolkit.
    factory_test_lists_path = os.path.join(options.path + TEST_LIST_DIR)
    insight_manager.loader.config_dir = factory_test_lists_path

  logging.info('Currently in the directory: %s',
               insight_manager.loader.config_dir)
  if options.subcommand == 'show':
    factory_objects = insight_manager.FindTarget(options.target,
                                                 options.testlist)
    if factory_objects is None:
      return
    for object_name, object_value in factory_objects.items():
      print(Colorize(object_name, color='MAGENTA'))
      print(object_value)
    if len(factory_objects) == 0:
      print("No matched test object is found.")
  elif options.subcommand == 'compare':
    insight_manager.ComparePytests(options.testlist_a, options.testlist_b)


if __name__ == '__main__':
  main(sys.argv[1:])
