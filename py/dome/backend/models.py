# Copyright 2016 The Chromium OS Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Umpire bundle wrapper

We don't take advantage of django's database functionality because this system
should ideally be stateless. In other words, all information should be kept in
umpire instead of the database. This may not be possible for now, since umpire
config still lacks some critical information such as the history record.

TODO(littlecvr): make umpire config complete such that it contains all the
                 information we need.
"""

import contextlib
import copy
import errno
import logging
import os
import re
import shutil
import stat
import subprocess
import tempfile
import traceback
import xmlrpclib

import django
import rest_framework.exceptions
import rest_framework.status
import yaml


# TODO(littlecvr): pull out the common parts between umpire and dome, and put
#                  them into a config file (using the new config API).
UMPIRE_BASE_PORT = 8080
UMPIRE_RPC_PORT_OFFSET = 2
UMPIRE_RSYNC_PORT_OFFSET = 4
UMPIRE_INSTALOG_SOCKET_PORT_OFFSET = 6
UMPIRE_CONFIG_BASENAME = 'umpire.yaml'
UMPIRE_RESOURCE_NAME_ALIAS = {
    'device_factory_toolkit': 'factory_toolkit',
    'rootfs_release': 'fsi',
    'server_factory_toolkit': 'factory_toolkit'}
UMPIRE_UPDATABLE_RESOURCE = set(['device_factory_toolkit',
                                 'firmware',
                                 'hwid',
                                 'rootfs_release',
                                 'server_factory_toolkit'])
UMPIRE_MATCH_KEY_MAP = {
    'macs': 'mac',
    'serial_numbers': 'sn',
    'mlb_serial_numbers': 'mlb_sn'}

# TODO(littlecvr): use volume container instead of absolute path.
# TODO(littlecvr): these constants are shared between here and cros_docker.sh,
#                  should be pulled out to common config.
FACTORY_SERVER_IMAGE_NAME = 'cros/factory_server'
DOCKER_SHARED_DIR = '/docker_shared'
UMPIRE_DOCKER_DIR = '/docker_shared/umpire'
UMPIRE_DEFAULT_BOARD_FILE = '.default_board'
UMPIRE_BASE_DIR_IN_UMPIRE_CONTAINER = '/var/db/factory/umpire'

# Mount point of the Umpire data folder in Dome's container. Note: this is not
# Umpire base directory in Umpire's container (which is also
# '/var/db/factory/umpire', but they have nothing to do with each other). This
# is also not Umpire's base directory on host (which is '/docker_shared/umpire'
# for now).
# TODO(littlecvr): shared between here and cros_docker.sh, should be pulled out
#                  to a common config.
UMPIRE_BASE_DIR = '/var/db/factory/umpire'

UMPIRED_FILEPATH = '/usr/local/factory/bin/umpired'


logger = logging.getLogger('django.%s' % __name__)


class DomeException(rest_framework.exceptions.APIException):
  """Virtual base class of all Dome exceptions."""

  def __init__(self, detail=None, status_code=None):
    self.status_code = status_code or self.status_code
    super(DomeException, self).__init__(detail)


class DomeClientException(DomeException):
  """Errors that can be fixed by the client."""

  status_code = rest_framework.status.HTTP_400_BAD_REQUEST


class DomeServerException(DomeException):
  """Errors that cannot be fixed by the client."""

  status_code = rest_framework.status.HTTP_500_INTERNAL_SERVER_ERROR


@contextlib.contextmanager
def UploadedFile(temporary_uploaded_file_id):
  f = TemporaryUploadedFile.objects.get(pk=temporary_uploaded_file_id).file
  try:
    yield f
  finally:
    f.close()
    path = UploadedFilePath(f)
    try:
      os.unlink(path)  # once the file has been used it can be removed
    except OSError as e:
      if e.errno != errno.ENOENT:  # don't care if it's been removed already
        raise
    try:
      os.rmdir(os.path.dirname(path))  # also try to remove empty directory
    except OSError as e:
      if e.errno != errno.ENOTEMPTY:  # but don't care if it's not empty
        raise


def UploadedFilePath(uploaded_file):
  return os.path.join(django.conf.settings.MEDIA_ROOT, uploaded_file.name)


@contextlib.contextmanager
def UmpireAccessibleFile(board, uploaded_file):
  """Make a file uploaded from Dome accessible by a specific Umpire container.

  This function:
  1. creates a temp folder in UMPIRE_BASE_DIR
  2. copies the uploaded file to the temp folder
  3. runs chmod on the folder and file to make sure Umpire is readable
  4. remove the temp folder at the end

  Note that we need to rename the file to its original basename. Umpire copies
  the file into its resources folder without renaming the incoming file (though
  it appends version and hash). If we don't do this, the umpire resources folder
  will soon be filled with many 'tmp.XXXXXX#{version}#{hash}', and it'll be hard
  to tell what the files actually are. Also, due to the way Umpire Docker is
  designed, it's not possible to move the file instead of copy now.

  TODO(littlecvr): make Umpire support renaming when updating.
  TODO(b/31417203): provide an argument to choose from moving file instead of
                    copying (after the issue has been solved).

  Args:
    board: name of the board (used to construct Umpire container's name).
    uploaded_file: file field of TemporaryUploadedFile.
  """
  # TODO(b/31417203): use volume container or named volume instead of
  #                   UMPIRE_BASE_DIR.
  temp_dir = tempfile.mkdtemp(dir=os.path.join(UMPIRE_BASE_DIR, board))

  try:
    new_path = os.path.join(temp_dir, os.path.basename(uploaded_file.name))
    shutil.copy(UploadedFilePath(uploaded_file), new_path)

    # make sure they're readable to umpire
    os.chmod(temp_dir, stat.S_IRWXU | stat.S_IROTH | stat.S_IXOTH)
    os.chmod(new_path, stat.S_IRWXU | stat.S_IROTH | stat.S_IXOTH)

    # The temp file:
    #   in Dome:   ${UMPIRE_BASE_DIR}/${board}/${temp_dir}/${name}
    #   in Umpire: ${UMPIRE_BASE_DIR}/${temp_dir}/${name}
    # so need to remove "${board}/"
    tokens = new_path.split('/')
    del tokens[-3]
    yield '/'.join(tokens)
  finally:
    try:
      shutil.rmtree(temp_dir)
    except OSError as e:
      # doesn't matter if the folder is removed already, otherwise, raise
      if e.errno != errno.ENOENT:
        raise


def GetUmpireServer(board_name):
  # get URL of the board
  board = Board.objects.get(pk=board_name).ReplaceLocalhostWithDockerHostIP()
  url = 'http://%s:%d' % (board.umpire_host,
                          board.umpire_port + UMPIRE_RPC_PORT_OFFSET)
  return xmlrpclib.ServerProxy(url, allow_none=True)


def GetUmpireStatus(board_name):
  return GetUmpireServer(board_name).GetStatus()


class TemporaryUploadedFile(django.db.models.Model):
  """Model to hold temporary uploaded files from user.

  The API of Dome is designed as: if a request contains N files, split it into
  (N+1) requests, with first N request uploading each file (encoded in
  multipart/form-data), and the last request sending other fields (encoded in
  JSON). Each file uploading request gets a file ID, in the last request, we
  refer to a file using its ID we got before.

  For example, if we want to send a request:
  {
    "foo": "bar",
    "hello": "world",
    "file01": a file object,
    "file02": another file object
  }
  We split it into 3 requests:
  1. Send {"file": a file object} in multipart/form-data, suppose we got ID
     1005.
  2. Send {"file": another file object} in multipart/form-data, suppose we got
     ID 1008.
  3. Send
     {
       "foo": "bar",
       "hello": "world",
       "file01": 1005,
       "file02": 1008
     }
     in JSON.
  """

  file = django.db.models.FileField(upload_to='%Y%m%d')
  created = django.db.models.DateTimeField(auto_now_add=True)

  # TODO(littlecvr): remove outdated files automatically


class Board(django.db.models.Model):

  # TODO(littlecvr): max_length should be shared with Umpire and serializer
  name = django.db.models.CharField(max_length=200, primary_key=True)
  umpire_enabled = django.db.models.BooleanField(default=False)
  umpire_host = django.db.models.GenericIPAddressField(null=True)
  umpire_port = django.db.models.PositiveIntegerField(null=True)

  # TODO(littlecvr): add TFTP and Overlord ports

  class Meta(object):
    ordering = ['name']

  def ReplaceLocalhostWithDockerHostIP(self):
    # Dome is inside a docker container. If umpire_host is 'localhost', it is
    # not actually 'localhost', it is the docker host instead of docker
    # container. So we need to transform it to the docker host's IP.
    if self.umpire_host in ['localhost', '127.0.0.1']:
      self.umpire_host = Board._GetHostIP()
    return self

  def AddExistingUmpireContainer(self, host, port):
    """Add an existing Umpire container to the database."""
    container_name = Board.GetUmpireContainerName(self.name)
    logger.info('Adding Umpire container %r', container_name)
    if not Board.DoesUmpireContainerExist(self.name):
      error_message = (
          'Container %s does not exist, Dome will not add a non-existing '
          'container into the database, please create a new one instead' %
          container_name)
      logger.error(error_message)
      raise DomeClientException(error_message)
    self.umpire_enabled = True
    self.umpire_host = host
    self.umpire_port = port
    self.save()
    return self

  def CreateUmpireContainer(self, port):
    """Create a local Umpire container from a factory toolkit."""
    # make sure the container does not exist
    container_name = Board.GetUmpireContainerName(self.name)
    logger.info('Creating Umpire container %r', container_name)
    if Board.DoesUmpireContainerExist(self.name):
      error_message = (
          'Container %s already exists, Dome will not try to create a new one, '
          'please add the existing one instead' % container_name)
      logger.error(error_message)
      raise DomeClientException(error_message)

    try:
      # create and start a new container
      # TODO(littlecvr): this is almost identical to cros_docker.sh's
      #                  do_umpire_run() function, we should remove this
      #                  function in that script because this job should be
      #                  done by Dome only
      cmd = [
          'docker', 'run', '--detach', '--privileged',
          '--volume', '/etc/localtime:/etc/localtime:ro',
          '--volume', '%s:/mnt' % DOCKER_SHARED_DIR,
          '--volume', '%s/%s:%s' % (UMPIRE_DOCKER_DIR,
                                    self.name,
                                    UMPIRE_BASE_DIR_IN_UMPIRE_CONTAINER),
          '--publish', '%d:%d' % (port, UMPIRE_BASE_PORT),
          '--publish', '%d:%d' % (port + UMPIRE_RPC_PORT_OFFSET,
                                  UMPIRE_BASE_PORT + UMPIRE_RPC_PORT_OFFSET),
          '--publish', '%d:%d' % (port + UMPIRE_RSYNC_PORT_OFFSET,
                                  UMPIRE_BASE_PORT + UMPIRE_RSYNC_PORT_OFFSET),
          '--publish', '%d:%d' % (port + UMPIRE_INSTALOG_SOCKET_PORT_OFFSET,
                                  UMPIRE_BASE_PORT +
                                  UMPIRE_INSTALOG_SOCKET_PORT_OFFSET),
          '--restart', 'unless-stopped',
          '--name', container_name,
          FACTORY_SERVER_IMAGE_NAME, UMPIRED_FILEPATH]
      logger.info('Running command %r', cmd)
      subprocess.check_call(cmd)
      # Update default board for 'cros_docker.sh umpire' commands.
      with open(os.path.join(UMPIRE_BASE_DIR,
                             UMPIRE_DEFAULT_BOARD_FILE), 'w') as f:
        f.write(self.name)
    except Exception:
      logger.error('Failed to create Umpire container %r', container_name)
      logger.exception(traceback.format_exc())
      # remove container
      subprocess.call(['docker', 'stop', container_name])
      subprocess.call(['docker', 'rm', container_name])
      raise

    # push into the database
    return self.AddExistingUmpireContainer('localhost', port)

  def DeleteUmpireContainer(self):
    logger.info('Deleting Umpire container %r', self.name)
    container_name = Board.GetUmpireContainerName(self.name)
    subprocess.call(['docker', 'stop', container_name])
    subprocess.call(['docker', 'rm', container_name])
    self.umpire_enabled = False
    self.umpire_host = None
    self.umpire_port = None
    self.save()
    return self

  @staticmethod
  def _GetHostIP():
    # An easy way to get IP of the host. It's possible to install python
    # packages such as netifaces or pynetinfo into the container, but that
    # requires gcc to be installed and will thus increase the size of the
    # container (which we don't want). Alpine itself provides the package as
    # well, but it's on the edge branch and cannot be easily installed using the
    # apk command.
    ip = subprocess.check_output(
        'ip route | grep "^default"', shell=True).split()[2]
    return ip.strip()  # remove the trailing newline

  @staticmethod
  def DoesUmpireContainerExist(name):
    container_name = Board.GetUmpireContainerName(name)
    container_list = subprocess.check_output([
        'docker', 'ps', '--all', '--format', '{{.Names}}']).splitlines()
    return container_name in container_list

  @staticmethod
  def GetUmpireContainerName(name):
    return 'umpire_%s' % name

  @staticmethod
  def CreateOne(name, **kwargs):
    logger.info('Creating new board %r', name)
    board = Board.objects.create(name=name)
    try:
      return Board.UpdateOne(board, **kwargs)
    except Exception:
      logger.error('Failed to create board %r', name)
      logger.exception(traceback.format_exc())
      # delete the entry if anything goes wrong
      try:
        Board.objects.get(pk=name).delete()
      except django.core.exceptions.ObjectDoesNotExist:
        pass
      except Exception:
        raise

  @staticmethod
  def UpdateOne(board, **kwargs):
    logger.info('Updating board %r', board.name)
    # enable or disable Umpire if necessary
    if ('umpire_enabled' in kwargs and
        board.umpire_enabled != kwargs['umpire_enabled']):
      if not kwargs['umpire_enabled']:
        board.DeleteUmpireContainer()
      else:
        if kwargs.get('umpire_add_existing_one', False):
          board.AddExistingUmpireContainer(kwargs['umpire_host'],
                                           kwargs['umpire_port'])
        else:  # create a new local instance
          board.CreateUmpireContainer(kwargs['umpire_port'])

    # update attributes assigned in kwargs
    for attr, value in kwargs.iteritems():
      if hasattr(board, attr):
        setattr(board, attr, value)
    board.save()

    return board


class Resource(object):

  def __init__(self, res_type, res_version, res_hash, updatable):
    self.type = res_type
    self.version = res_version
    self.hash = res_hash
    self.updatable = updatable

  # TODO(littlecvr): Umpire may have the same function already
  @staticmethod
  def ParseName(resource_filename):
    """Parse a resource name and return its basename, version, and hash."""
    match = re.match(r'^([^#]*)#([^#]*)#([^#]*)$', resource_filename)
    return {
        'basename': match.group(1),
        'version': match.group(2),
        'hash': match.group(3)
    }

  @staticmethod
  def CreateOne(board_name, resource_type, resource_file_id):
    umpire_server = GetUmpireServer(board_name)
    with UploadedFile(resource_file_id) as f:
      with UmpireAccessibleFile(board_name, f) as p:
        resource_filename = umpire_server.AddResource(p, resource_type)
    parsed = Resource.ParseName(resource_filename)
    return Resource(resource_type,
                    parsed['version'],
                    parsed['hash'],
                    resource_type in UMPIRE_UPDATABLE_RESOURCE)


# TODO(littlecvr): should merge into BundleModel
class Bundle(object):
  """Represent a bundle in umpire."""

  def __init__(self, name, note, active, resources, rules):
    self.name = name
    self.note = note
    self.active = active

    # Parse resources. A resource in umpire config is a simple key-value
    # mapping, with its value consists of {file_name}, {version}, and {hash}:
    #   {resource_type}: {file_name}#{version}#{hash}
    # We'll parse its value for the front-end:
    #   {resource_type}: {
    #       'version': {version},
    #       'hash': {hash},
    #       'updatable': whether or not the resource can be updated}
    self.resources = {}
    for res_type in resources:
      match = re.match(r'^[^#]*#([^#]*)#([^#]*)$', resources[res_type])
      if match and len(match.groups()) >= 2:
        self.resources[res_type] = Resource(
            res_type,  # type
            match.group(1),  # version
            match.group(2),  # hash
            res_type in UMPIRE_UPDATABLE_RESOURCE)  # updatable

    self.rules = {}
    for umpire_key in rules:
      key = next(
          k for (k, v) in UMPIRE_MATCH_KEY_MAP.iteritems() if v == umpire_key)
      self.rules[key] = rules[umpire_key]

  @staticmethod
  def _GetNormalizedActiveConfig(board_name):
    """Return the normalized version of Umpire active config."""
    umpire_status = GetUmpireStatus(board_name)
    config = yaml.load(umpire_status['active_config'])
    return Bundle._NormalizeConfig(config)

  @staticmethod
  def _UploadAndDeployConfig(board_name, config, force=False):
    """Upload and deploy config atomically."""
    umpire_server = GetUmpireServer(board_name)
    staging_config_path = umpire_server.UploadConfig(
        UMPIRE_CONFIG_BASENAME, yaml.dump(config, default_flow_style=False))

    try:
      umpire_server.StageConfigFile(staging_config_path, force)
    except Exception as e:
      raise EnvironmentError('Cannot stage config file, make sure no one is '
                             'editing Umpire config at the same time, and '
                             'there is no staging config exists. Error '
                             'message: %r' % e)

    try:
      umpire_server.Deploy(staging_config_path)
    except Exception as e:
      umpire_server.UnstageConfigFile()
      raise RuntimeError('Cannot deploy Umpire config, error message: %r' % e)

  @staticmethod
  def _NormalizeConfig(config):
    bundle_id_set = set(b['id'] for b in config['bundles'])

    # We do not allow multiple rulesets referring to the same bundle, so
    # duplicate the bundle if we have found such cases.
    ruleset_id_set = set()
    for r in config['rulesets']:
      # TODO(littlecvr): how to deal with a ruleset that refers to a
      #                  non-existing bundle?

      if r['bundle_id'] not in ruleset_id_set:
        ruleset_id_set.add(r['bundle_id'])
      else:  # need to duplicate
        # generate a new name, may generate very long _copy_copy_copy... at the
        # end if there are many conflicts
        new_name = r['bundle_id']
        while True:
          new_name = '%s_copy' % new_name
          if new_name not in ruleset_id_set and new_name not in bundle_id_set:
            ruleset_id_set.add(new_name)
            bundle_id_set.add(new_name)
            break

        # find the original bundle and duplicate it
        src_bundle = next(
            b for b in config['bundles'] if b['id'] == r['bundle_id'])
        dst_bundle = copy.deepcopy(src_bundle)
        dst_bundle['id'] = new_name
        config['bundles'].append(dst_bundle)

        # update the ruleset
        r['bundle_id'] = new_name

    # sort 'bundles' section by their IDs
    config['bundles'].sort(key=lambda b: b['id'])

    # We do not allow bundles exist in 'bundles' section but not in 'ruleset'
    # section.
    for b in config['bundles']:
      if b['id'] not in ruleset_id_set:
        ruleset_id_set.add(b['id'])
        config['rulesets'].append({'active': False,
                                   'bundle_id': b['id'],
                                   'note': b['note']})

    return config

  def DeleteOne(self, bundle_name):
    """Delete a bundle in Umpire config.

    Args:
      bundle_name: the bundle to delete.
    """
    config = self._GetNormalizedActiveConfig()

    config['rulesets'] = [
        r for r in config['rulesets'] if r['bundle_id'] != bundle_name]
    config['bundles'] = [
        b for b in config['bundles'] if b['id'] != bundle_name]

    self._UploadAndDeployConfig(config)

  @staticmethod
  def ListOne(board_name, bundle_name):
    """Return the bundle that matches the search criterion.

    Args:
      board_name: name of the board.
      bundle_name: name of the bundle to find, this corresponds to the "id"
          field in umpire config.
    """
    config = Bundle._GetNormalizedActiveConfig(board_name)

    ruleset = next(
        r for r in config['rulesets'] if r['bundle_id'] == bundle_name)
    active = ruleset['active']
    rules = ruleset.get('match', {})

    bundle = next(b for b in config['bundles'] if b['id'] == bundle_name)

    return Bundle(bundle['id'],  # name
                  bundle['note'],  # note
                  active,  # active
                  bundle['resources'],  # resources
                  rules)  # matching rules

  @staticmethod
  def ListAll(board_name):
    """Return all bundles as a list.

    This function lists bundles in the following order:
    1. bundles in the 'rulesets' section
    2. bundles in the 'bunedles' section but not in the 'rulesets' section

    Args:
      board_name: name of the board.

    Return:
      A list of all bundles.
    """
    config = Bundle._GetNormalizedActiveConfig(board_name)

    bundle_dict = dict((b['id'], b) for b in config['bundles'])

    bundle_list = list()
    for r in config['rulesets']:
      b = bundle_dict[r['bundle_id']]
      bundle_list.append(Bundle(b['id'],
                                r['note'],
                                r['active'],
                                b['resources'],
                                r.get('match', {})))

    return bundle_list

  def ModifyOne(self, name, active=None, rules=None):
    """Modify a bundle.

    Args:
      name: name of the bundle.
      active: True to make the bundle active, False to make the bundle inactive.
          None means no change.
      rules: rules to replace, this corresponds to Umpire's "match", see
          Umpire's doc for more info, None means no change.
    """
    config = self._GetNormalizedActiveConfig()
    bundle = next(b for b in config['rulesets'] if b['bundle_id'] == name)

    if active is not None:
      bundle['active'] = active

    if rules is not None:
      bundle['match'] = {}
      for key in rules:
        if rules[key]:  # add non-empty key only
          bundle['match'][UMPIRE_MATCH_KEY_MAP[key]] = map(str, rules[key])
    else:
      bundle.pop('match', None)

    self._UploadAndDeployConfig(config)

    return self.ListOne(bundle['bundle_id'])

  @staticmethod
  def ReorderBundles(board_name, new_order):
    """Reorder the bundles in Umpire config.

    TODO(littlecvr): make sure this also works if multiple users are using at
                     the same time.

    Args:
      new_order: a list of bundle names.
    """
    old_config = Bundle._GetNormalizedActiveConfig(board_name)

    # make sure all names are in current config
    old_bundle_set = set(b['id'] for b in old_config['bundles'])
    new_bundle_set = set(new_order)
    if old_bundle_set != new_bundle_set:
      raise DomeClientException('All bundles must be listed when reordering')

    # build a map for fast query later
    rulesets = dict((r['bundle_id'], r) for r in old_config['rulesets'])

    # reorder bundles
    new_config = old_config.copy()
    new_config['rulesets'] = [rulesets[n] for n in new_order]

    Bundle._UploadAndDeployConfig(board_name, new_config)

    return Bundle.ListAll(board_name)

  def UpdateResource(self, src_bundle_name, dst_bundle_name, note,
                     resource_type, resource_file_id):
    """Update resource in a bundle.

    Args:
      src_bundle_name: the bundle to update.
      dst_bundle_name: if specified, make a copy of the original bundle and name
          it as dst_bundle_name first. Otherwise, update-in-place. (See umpire's
          Update function).
      note: if dst bundle is specified, this will be note of the dst bundle;
          otherwise, this will overwrite note of the src bundle.
      resource_type: type of resource to update.
      resource_file_id: id of the resource file (id of TemporaryUploadedFile).
    """
    # Replace with the alias if needed.
    resource_type = UMPIRE_RESOURCE_NAME_ALIAS.get(resource_type, resource_type)

    with UploadedFile(resource_file_id) as f:
      with UmpireAccessibleFile(self.board, f) as p:
        self.umpire_server.Update([(resource_type, p)],
                                  src_bundle_name,
                                  dst_bundle_name)

    # Umpire does not allow the user to add bundle note directly via update. So
    # duplicate the source bundle first.
    self.umpire_status = self.umpire_server.GetStatus()
    config = yaml.load(self.umpire_status['staging_config'])

    # find source bundle
    src_bundle = None
    for b in config['rulesets']:
      if src_bundle_name == b['bundle_id']:
        src_bundle = b

    if not dst_bundle_name:  # in-place update
      src_bundle['note'] = str(note)

      # also update note in the bundles section
      for b in config['bundles']:
        if src_bundle_name == b['id']:
          b['note'] = str(note)
    else:
      # copy source bundle
      dst_bundle = src_bundle.copy()
      dst_bundle['bundle_id'] = str(dst_bundle_name)
      dst_bundle['note'] = str(note)
      config['rulesets'].insert(0, dst_bundle)

      # also update note in the bundles section
      for b in config['bundles']:
        if dst_bundle_name == b['id']:
          b['note'] = str(note)

    # config staged before, need the force argument or Umpire will complain
    self._UploadAndDeployConfig(config, force=True)

    return self.ListOne(dst_bundle_name or src_bundle_name)

  @staticmethod
  def UploadNew(board_name, bundle_name, bundle_note, bundle_file_id):
    """Upload a new bundle.

    Args:
      board_name: name of the board.
      bundle_name: name of the new bundle, in string. This corresponds to the
          "id" field in umpire config.
      bundle_note: commit message. This corresponds to the "note" field in
          umpire config.
      bundle_file_id: id of the bundle file (id of TemporaryUploadedFile).

    Return:
      The newly created bundle.
    """
    umpire_server = GetUmpireServer(board_name)

    with UploadedFile(bundle_file_id) as f:
      with UmpireAccessibleFile(board_name, f) as p:
        try:
          umpire_server.ImportBundle(p, bundle_name, bundle_note)
        except xmlrpclib.Fault as e:
          if 'already in use' in e.faultString:
            raise DomeClientException(
                detail='Bundle "%s" already exists' % bundle_name,
                status_code=rest_framework.status.HTTP_409_CONFLICT)
          else:
            raise DomeServerException(detail=e.faultString)

    config = yaml.load(umpire_server.GetStatus()['staging_config'])
    for ruleset in config['rulesets']:
      if ruleset['bundle_id'] == bundle_name:
        # TODO(b/34264367): support unicde.
        ruleset['note'] = str(bundle_note)
        ruleset['active'] = True
        break

    Bundle._UploadAndDeployConfig(board_name, config, force=True)

    # find and return the new bundle
    return Bundle.ListOne(board_name, bundle_name)
