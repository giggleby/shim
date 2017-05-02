# Copyright 2014 The Chromium OS Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Common Umpire classes.

This module provides constants and common Umpire classes.
"""

import filecmp
import logging
import os
import shutil
import tempfile

import factory_common  # pylint: disable=W0611
from cros.factory.tools import get_version
from cros.factory.umpire import common
from cros.factory.umpire import config
from cros.factory.umpire import shop_floor_manager
from cros.factory.umpire import utils
from cros.factory.utils import file_utils


# File name under base_dir
_ACTIVE_UMPIRE_CONFIG = 'active_umpire.yaml'
_STAGING_UMPIRE_CONFIG = 'staging_umpire.yaml'
_UMPIRED_PID_FILE = 'umpired.pid'
_UMPIRED_LOG_FILE = 'umpired.log'
_DEVICE_TOOLKITS_DIR = os.path.join('toolkits', 'device')
_UMPIRE_DATA_DIR = 'umpire_data'
_RESOURCES_DIR = 'resources'
_CONFIG_DIR = 'conf'
_LOG_DIR = 'log'
_PID_DIR = 'run'
_WEBAPP_PORT_OFFSET = 1
_CLI_PORT_OFFSET = 2
_RPC_PORT_OFFSET = 3
_RSYNC_PORT_OFFSET = 4
_HTTP_POST_PORT_OFFSET = 5
_INSTALOG_SOCKET_PORT_OFFSET = 6
_INSTALOG_HTTP_PORT_OFFSET = 7
# shopfloor XMLRPC port ranges starts at base_port + _SHOPFLOOR_PORTS_OFFSET.
_SHOPFLOOR_PORTS_OFFSET = 10


def GetRsyncPortFromBasePort(base_port):
  return base_port + _RSYNC_PORT_OFFSET


def GetInstalogPortFromBasePort(base_port):
  return base_port + _INSTALOG_SOCKET_PORT_OFFSET


class UmpireEnv(object):
  """Provides accessors of Umpire resources.

  The base directory is obtained in constructor. If a user wants to run
  locally (e.g. --local is used), just modify self.base_dir to local
  directory and the accessors will reflect the change.

  Properties:
    base_dir: Umpire base directory
    config_path: Path of the Umpire Config file
    config: Active UmpireConfig object
    staging_config: Staging UmpireConfig object
    shop_floor_manager: ShopFloorManager instance
  """
  # List of Umpire mandatory subdirectories.
  # Use tuple to avoid modifying.
  SUB_DIRS = ('bin', 'dashboard', 'log', 'resources', 'run', 'toolkits',
              'updates', 'conf', 'umpire_data')

  def __init__(self, root_dir='/'):
    self.base_dir = os.path.join(root_dir, common.DEFAULT_BASE_DIR)
    self.server_toolkit_dir = os.path.join(root_dir, common.DEFAULT_SERVER_DIR)
    self.config_path = None
    self.config = None
    self.staging_config = None
    self.shop_floor_manager = None

  @property
  def device_toolkits_dir(self):
    return os.path.join(self.base_dir, _DEVICE_TOOLKITS_DIR)

  @property
  def resources_dir(self):
    return os.path.join(self.base_dir, _RESOURCES_DIR)

  @property
  def config_dir(self):
    return os.path.join(self.base_dir, _CONFIG_DIR)

  @property
  def log_dir(self):
    return os.path.join(self.base_dir, _LOG_DIR)

  @property
  def pid_dir(self):
    return os.path.join(self.base_dir, _PID_DIR)

  @property
  def umpire_data_dir(self):
    return os.path.join(self.base_dir, _UMPIRE_DATA_DIR)

  @property
  def active_config_file(self):
    return os.path.join(self.base_dir, _ACTIVE_UMPIRE_CONFIG)

  @property
  def staging_config_file(self):
    return os.path.join(self.base_dir, _STAGING_UMPIRE_CONFIG)

  @property
  def umpire_ip(self):
    if not self.config:
      raise common.UmpireError('UmpireConfig not loaded yet.')
    return self.config.get('ip', '0.0.0.0')

  @property
  def umpire_base_port(self):
    if not self.config:
      raise common.UmpireError('UmpireConfig not loaded yet.')
    return self.config.get('port', common.UMPIRE_DEFAULT_PORT)

  @property
  def umpire_webapp_port(self):
    return self.umpire_base_port + _WEBAPP_PORT_OFFSET

  @property
  def umpire_cli_port(self):
    return self.umpire_base_port + _CLI_PORT_OFFSET

  @property
  def umpire_rpc_port(self):
    return self.umpire_base_port + _RPC_PORT_OFFSET

  @property
  def umpire_rsync_port(self):
    return GetRsyncPortFromBasePort(self.umpire_base_port)

  @property
  def umpire_http_post_port(self):
    return self.umpire_base_port + _HTTP_POST_PORT_OFFSET

  @property
  def umpire_instalog_socket_port(self):
    return GetInstalogPortFromBasePort(self.umpire_base_port)

  @property
  def umpire_instalog_http_port(self):
    return self.umpire_base_port + _INSTALOG_HTTP_PORT_OFFSET

  @property
  def shopfloor_start_port(self):
    return self.umpire_base_port + _SHOPFLOOR_PORTS_OFFSET

  def ReadConfig(self, custom_path=None):
    """Reads Umpire config.

    It just returns config. It doesn't change config in property.

    Args:
      custom_path: If specified, load the config file custom_path pointing to.
          Default loads active config.

    Returns:
      UmpireConfig object.
    """
    config_path = custom_path or self.active_config_file
    return config.UmpireConfig(config_path)

  def LoadConfig(self, custom_path=None, init_shop_floor_manager=True,
                 validate=True):
    """Loads Umpire config file and validates it.

    Also, if init_shop_floor_manager is True, it also initializes
    ShopFloorManager.

    Args:
      custom_path: If specified, load the config file custom_path pointing to.
      init_shop_floor_manager: True to init ShopFloorManager object.
      validate: True to validate resources in config.

    Raises:
      UmpireError if it fails to load the config file.
    """
    def _LoadValidateConfig(path):
      result = config.UmpireConfig(path)
      if validate:
        config.ValidateResources(result, self)
      return result

    def _InitShopFloorManager():
      # Can be obtained after a valid config is loaded.
      port_start = self.shopfloor_start_port
      if port_start:
        self.shop_floor_manager = shop_floor_manager.ShopFloorManager(
            port_start, port_start + config.NUMBER_SHOP_FLOOR_HANDLERS)

    # Load active config & update config_path.
    config_path = custom_path or self.active_config_file
    logging.debug('Load %sconfig: %s', 'active ' if not custom_path else '',
                  config_path)
    # Note that config won't be set if it fails to load/validate the new config.
    self.config = _LoadValidateConfig(config_path)
    self.config_path = config_path

    if init_shop_floor_manager:
      _InitShopFloorManager()

  def HasStagingConfigFile(self):
    """Checks if a staging config file exists.

    Returns:
      True if a staging config file exists.
    """
    return os.path.isfile(self.staging_config_file)

  def StageConfigFile(self, config_path=None, force=False):
    """Stages a config file.

    Args:
      config_path: a config file to mark as staging. Default: active file.
      force: True to stage the file even if it already has staging file.
    """
    if not force and self.HasStagingConfigFile():
      raise common.UmpireError(
          'Unable to stage a config file as another config is already staged. '
          'Check %r to decide if it should be deployed (use "umpire deploy"), '
          'edited again ("umpire edit") or discarded ("umpire unstage").' %
          self.staging_config_file)

    if config_path is None:
      config_path = self.active_config_file

    source = os.path.realpath(config_path)
    if not os.path.isfile(source):
      raise common.UmpireError(
          "Unable to stage config %s as it doesn't exist." % source)
    if force and self.HasStagingConfigFile():
      logging.info('Force staging, unstage existing one first.')
      self.UnstageConfigFile()
    logging.info('Stage config: ' + source)
    file_utils.SymlinkRelative(source, self.staging_config_file,
                               base=self.base_dir)

  def UnstageConfigFile(self):
    """Unstage the current staging config file.

    Returns:
      Real path of the staging file being unstaged.
    """
    if not self.HasStagingConfigFile():
      raise common.UmpireError(
          "Unable to unstage as there's no staging config file.")
    staging_real_path = os.path.realpath(self.staging_config_file)
    logging.info('Unstage config: ' + staging_real_path)
    os.unlink(self.staging_config_file)
    return staging_real_path

  def ActivateConfigFile(self, config_path=None):
    """Activates a config file.

    Args:
      config_path: a config file to mark as active. Default: use staging file.
    """
    if config_path is None:
      config_path = self.staging_config_file

    if not os.path.isfile(config_path):
      raise common.UmpireError(
          'Unable to activate missing config: ' + config_path)

    config_to_activate = os.path.realpath(config_path)
    if os.path.isfile(self.active_config_file):
      logging.info('Deactivate config: ' +
                   os.path.realpath(self.active_config_file))
      os.unlink(self.active_config_file)
    logging.info('Activate config: ' + config_to_activate)
    file_utils.SymlinkRelative(config_to_activate, self.active_config_file,
                               base=self.base_dir)

  def AddResource(self, file_name, res_type=None):
    """Adds a file into base_dir/resources.

    Args:
      file_name: file to be added.
      res_type: (optional) resource type. If specified, it is one of the enum
        ResourceType. It tries to get version and fills in resource file name
        <base_name>#<version>#<hash>.

    Returns:
      Resource file name (full path).
    """
    def TryGetVersion():
      """Tries to get version of the given file with res_type.

      Now it can retrieve version only from file of FIRMWARE, ROOTFS_RELEASE
      and ROOTFS_TEST resource type.

      Returns:
        version string if found. '' if type is not supported or version
        failed to obtain.
      """
      if res_type is None:
        return ''

      if res_type == common.ResourceType.FIRMWARE:
        bios, ec, pd = None, None, None
        # pylint: disable=W0632
        if file_name.endswith('.gz'):
          bios, ec, pd = get_version.GetFirmwareVersionsFromOmahaChannelFile(
              file_name)
        else:
          bios, ec, pd = get_version.GetFirmwareVersions(file_name)
        return '%s:%s:%s' % (bios or '', ec or '', pd or '')

      if (res_type == common.ResourceType.ROOTFS_RELEASE or
          res_type == common.ResourceType.ROOTFS_TEST):
        res_version = get_version.GetReleaseVersionFromOmahaChannelFile(
            file_name)
        return res_version or ''

      if res_type == common.ResourceType.HWID:
        res_version = get_version.GetHWIDVersion(file_name)
        return res_version or ''

      return ''

    file_utils.CheckPath(file_name, 'source')

    # Remove version and hash (everything after the '#' character). Otherwise,
    # if the source file contains them already, the destination file will
    # contain multiple version/hash strings.
    basename = os.path.basename(file_name).partition('#')[0]
    res_version = TryGetVersion()
    md5 = file_utils.MD5InHex(file_name)[:common.RESOURCE_HASH_DIGITS]

    res_file_name = os.path.join(
        self.resources_dir,
        '#'.join([basename, res_version, md5]))

    if os.path.isfile(res_file_name):
      if filecmp.cmp(file_name, res_file_name, shallow=False):
        logging.warning('Skip copying as file already exists: %s',
                        res_file_name)
        return res_file_name
      else:
        raise common.UmpireError(
            'Hash collision: file %r != resource file %r' % (file_name,
                                                             res_file_name))
    else:
      file_utils.AtomicCopy(file_name, res_file_name)
      logging.info('Resource added: %s', res_file_name)
      return res_file_name

  def GetResourcePath(self, resource_name, check=True):
    """Gets a resource's full path.

    Args:
      resource_name: resource name.
      check: True to check if the resource exists.

    Returns:
      Full path of the resource.

    Raises:
      IOError if the resource does not exist.
    """
    path = os.path.join(self.resources_dir, resource_name)
    if check:
      file_utils.CheckPath(path, 'resource')
    return path

  def InResource(self, path):
    """Checks if path points to a file in resources directory.

    Args:
      path: Either a full-path of a file or a file's basename.

    Returns:
      True if the path points to a file in resources directory.
    """
    dirname = os.path.dirname(path)
    if not dirname:
      path = self.GetResourcePath(path, check=False)
    elif dirname != self.resources_dir:
      return False
    return os.path.isfile(path)

  def GetBundleDeviceToolkit(self, bundle_id):
    """Gets a bundle's device toolkit path.

    Args:
      bundle_id: bundle ID.

    Returns:
      Full path of extracted device toolkit path.
      None if bundle_id is invalid.
    """
    bundle = self.config.GetBundle(bundle_id)
    if not bundle:
      return None
    resources = bundle.get('resources')
    if not resources:
      return None
    toolkit_resource = resources.get('device_factory_toolkit')
    if not toolkit_resource:
      return None
    toolkit_hash = utils.GetHashFromResourceName(toolkit_resource)
    toolkit_path = os.path.join(self.device_toolkits_dir, toolkit_hash)
    if not os.path.isdir(toolkit_path):
      return None
    return toolkit_path


class UmpireEnvForTest(UmpireEnv):
  """An UmpireEnv for other unittests.

  It creates a temp directory as its base directory and creates fundamental
  subdirectories (those which define property). The temp directory is removed
  once it is deleted.
  """

  def __init__(self):
    self.root_dir = tempfile.mkdtemp()
    super(UmpireEnvForTest, self).__init__(self.root_dir)
    os.makedirs(self.server_toolkit_dir)
    for fundamental_subdir in (
        self.config_dir,
        self.log_dir,
        self.pid_dir,
        self.resources_dir,
        self.umpire_data_dir):
      os.makedirs(fundamental_subdir)

    # Create dummy resource files.
    for res in ('complete.gz',
                'efi.gz',
                'firmware.gz',
                'hwid.gz',
                'oem.gz',
                'rootfs-release.gz',
                'rootfs-test.gz',
                'install_factory_toolkit.run',
                'state.gz',
                'vmlinuz'):
      file_utils.TouchFile(os.path.join(
          self.resources_dir, '%s##%s' % (res, common.EMPTY_FILE_HASH)))

  def Close(self):
    if os.path.isdir(self.root_dir):
      shutil.rmtree(self.root_dir)
