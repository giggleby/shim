#!/usr/bin/env python3
#
# Copyright 2017 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Integration tests for umpire docker.

This test would take some time to finish. Ideally this should be run when
there's umpire / docker related changes.

This test is assumed to be run inside docker using `setup/cros_docker.sh
umpire test`, and should not be run directly.
"""

import contextlib
import glob
import gzip
import json
import logging
import os
import re
import shutil
import subprocess
import tarfile
import time
import unittest
import xmlrpc.client

import requests

from cros.factory.umpire import common
from cros.factory.utils import file_utils
from cros.factory.utils import json_utils
from cros.factory.utils import net_utils
from cros.factory.utils import process_utils
from cros.factory.utils import sync_utils
from cros.factory.utils import time_utils


DOCKER_IMAGE_NAME = 'cros/factory_server'

BASE_DIR = os.path.dirname(__file__)
SETUP_DIR = os.path.abspath(
    os.path.join(BASE_DIR, '..', '..', '..', '..', 'setup'))
SCRIPT_PATH = os.path.join(SETUP_DIR, 'cros_docker.sh')

HOST_BASE_DIR = os.environ.get('TMPDIR', '/tmp')
HOST_SHARED_DIR = os.path.join(HOST_BASE_DIR, 'cros_docker')

DOCKER_BASE_DIR = '/var/db/factory/umpire/'
DOCKER_RESOURCE_DIR = os.path.join(DOCKER_BASE_DIR, 'resources')

TESTDATA_DIR = os.path.join(BASE_DIR, 'testdata')
SHARED_TESTDATA_DIR = os.path.join(TESTDATA_DIR, 'cros_docker')
UMPIRE_TESTDATA_DIR = os.path.join(TESTDATA_DIR, 'umpire')
CONFIG_TESTDATA_DIR = os.path.join(TESTDATA_DIR, 'config')


def _RunCrosDockerCommand(project_name, port, *args):
  """Run cros_docker.sh commands with environment variables for testing set."""
  subprocess.check_call(
      [SCRIPT_PATH] + list(args), env={
          'PROJECT': project_name,
          'UMPIRE_PORT': str(port),
          'HOST_SHARED_DIR': HOST_SHARED_DIR
      })


def _WaitForUmpireReady(rpc_addr):
  with xmlrpc.client.ServerProxy(rpc_addr) as proxy:

    def _IsReady():
      try:
        return not proxy.IsDeploying()
      except Exception:
        return False

    return sync_utils.WaitFor(_IsReady, 10)

class _UmpireInformation():

  def __init__(self, project_name):
    self.port = net_utils.FindUnusedPort(tcp_only=True, length=5)
    self.addr_base = f'http://localhost:{self.port}'
    self.rpc_addr_base = f'http://localhost:{self.port + 2}'
    self.project_name = project_name
    self.container_name = 'umpire_' + project_name
    self.umpire_dir = os.path.join(HOST_SHARED_DIR, 'umpire', self.project_name)
    self.resource_dir = os.path.join(self.umpire_dir, 'resources')


def _CopyTestData(umpire_dir, setup_shared_data):
  logging.info('Copying test data...')
  if setup_shared_data:
    shutil.copytree(SHARED_TESTDATA_DIR, HOST_SHARED_DIR, symlinks=True)
  shutil.copytree(UMPIRE_TESTDATA_DIR, umpire_dir, symlinks=True)
  for sub_dir in ('conf', 'log', 'run', 'temp', 'umpire_data'):
    os.mkdir(os.path.join(umpire_dir, sub_dir))


def _CloseServerProxyConnection(proxy):
  """Release the underlying resource in ServerProxy."""
  return proxy("close")()


def CleanUp(project_name, port):
  """Cleanup everything."""
  logging.info('Doing cleanup...')
  _RunCrosDockerCommand(project_name, port, 'umpire', 'destroy')
  shutil.rmtree(HOST_SHARED_DIR, ignore_errors=True)


def SetUpUmpire(project_name, port, umpire_dir, rpc_addr,
                setup_shared_data=False):
  try:
    logging.info('Starting umpire container %s on port %s', project_name, port)

    _CopyTestData(umpire_dir, setup_shared_data)

    logging.info('Starting umpire...')
    _RunCrosDockerCommand(project_name, port, 'umpire', 'run')

    logging.info('Waiting umpire to be started...')

    _WaitForUmpireReady(rpc_addr)
  except:
    CleanUp(project_name, port)
    raise


def PrintDockerLogs(container_name):
  if logging.getLogger().isEnabledFor(logging.DEBUG):
    docker_logs = subprocess.check_output(['docker', 'logs', container_name],
                                          stderr=subprocess.STDOUT)
    logging.debug(docker_logs)


class UmpireDockerTestCase(unittest.TestCase):
  """Base class for integration tests for umpire docker.

  Since starting / stopping umpire docker takes some time, we group several
  tests together, and only do starting / stopping once for each group of tests.
  """
  @classmethod
  def setUpClass(cls):
    # Add a timestamp to project name to avoid problem that sometimes container
    # goes dead.
    project_name = 'test_' + time.strftime('%Y%m%d_%H%M%S')
    cls.umpire = _UmpireInformation(project_name)
    SetUpUmpire(cls.umpire.project_name, cls.umpire.port, cls.umpire.umpire_dir,
                cls.umpire.rpc_addr_base, setup_shared_data=True)

  @classmethod
  def tearDownClass(cls):
    PrintDockerLogs(cls.umpire.container_name)
    CleanUp(cls.umpire.project_name, cls.umpire.port)

  @contextlib.contextmanager
  def assertRPCRaises(self,
                      exception=None,
                      fault_code=xmlrpc.client.APPLICATION_ERROR):
    """Assert that an RPC call raised exception.

    Args:
      exception: Substring that should be in returned exception string.
      fault_code: Expected faultCode for XML RPC.
    """
    with self.assertRaises(xmlrpc.client.Fault) as cm:
      yield
    self.assertEqual(fault_code, cm.exception.faultCode)
    if exception:
      self.assertIn(exception, cm.exception.faultString)


class TwoUmpireDockerTestCase(UmpireDockerTestCase):

  @classmethod
  def setUpClass(cls):
    super().setUpClass()
    project_name = 'test2_' + time.strftime('%Y%m%d_%H%M%S')
    cls.second_umpire = _UmpireInformation(project_name)
    SetUpUmpire(cls.second_umpire.project_name, cls.second_umpire.port,
                cls.second_umpire.umpire_dir, cls.second_umpire.rpc_addr_base)

  @classmethod
  def tearDownClass(cls):
    super().tearDownClass()
    PrintDockerLogs(cls.second_umpire.container_name)
    CleanUp(cls.second_umpire.project_name, cls.second_umpire.port)


class ResourceMapTest(UmpireDockerTestCase):
  """Tests for Umpire /webapps/resourcemap and legacy /resourcemap."""

  def testResourceMap(self):
    r = requests.get(f'{self.umpire.addr_base}/webapps/resourcemap',
                     headers={'X-Umpire-DUT': 'mac=00:11:22:33:44:55'})
    self.assertEqual(200, r.status_code)
    self.assertIsNotNone(
        re.search(r'^payloads: .*\.json$', r.text, re.MULTILINE))

  def testLegacyResourceMap(self):
    r = requests.get(f'{self.umpire.addr_base}/resourcemap',
                     headers={'X-Umpire-DUT': 'mac=00:11:22:33:44:55'})
    self.assertEqual(200, r.status_code)
    self.assertIsNotNone(
        re.search(r'^payloads: .*\.json$', r.text, re.MULTILINE))


class DownloadSlotsManagerTest(UmpireDockerTestCase):
  """Tests for Umpire /webapps/download_slots."""

  def testCanRequestSlot(self):
    r = requests.get(f'{self.umpire.addr_base}/webapps/download_slots',
                     headers={'X-Umpire-DUT': 'uuid='})
    self.assertEqual(200, r.status_code)
    self.assertIsNotNone(
        re.search(r'^UUID: [\w-]+',
                  r.text, re.MULTILINE))
    self.assertIsNotNone(re.search(r'^N_PLACE: 0$', r.text, re.MULTILINE))

  def testExtendAliveTimeSlot(self):
    r = requests.get(f'{self.umpire.addr_base}/webapps/download_slots',
                     headers={'X-Umpire-DUT': 'uuid='})
    self.assertEqual(200, r.status_code)
    res = re.search(r'^UUID: ([\w-]+)$', r.text, re.MULTILINE)
    self.assertIsNotNone(res)

    r = requests.get(f'{self.umpire.addr_base}/webapps/download_slots',
                     headers={'X-Umpire-DUT': f'uuid={res.group(1)}'})
    self.assertEqual(200, r.status_code)
    self.assertIsNotNone(
        re.search(r'^UUID: ('
                  f'{res.group(1)})$', r.text, re.MULTILINE))


class UmpireRPCTest(UmpireDockerTestCase):
  """Tests for Umpire RPC."""

  def setUp(self):
    super().setUp()
    self.proxy = xmlrpc.client.ServerProxy(self.umpire.rpc_addr_base)
    self.default_config = json.loads(
        self.ReadConfigTestdata('umpire_default.json'))
    # Deploy an empty default config.
    conf = self.proxy.AddConfigFromBlob(
        json.dumps(self.default_config), 'umpire_config')
    self.proxy.Deploy(conf)
    self.addCleanup(_CloseServerProxyConnection, self.proxy)

  def ReadConfigTestdata(self, name):
    return file_utils.ReadFile(os.path.join(CONFIG_TESTDATA_DIR, name))

  def testVersion(self):
    self.assertEqual(common.UMPIRE_VERSION, self.proxy.GetVersion())

  def testListMethods(self):
    self.assertIn('IsDeploying', self.proxy.system.listMethods())

  def testEndingSlashInProxyAddress(self):
    with xmlrpc.client.ServerProxy(self.umpire.rpc_addr_base) as proxy:
      self.assertIn('IsDeploying', proxy.system.listMethods())

  def testGetActiveConfig(self):
    self.assertEqual(self.default_config,
                     json.loads(self.proxy.GetActiveConfig()))

  def testAddConfigFromBlob(self):
    test_add_config_blob = 'test config blob'
    conf = self.proxy.AddConfigFromBlob(test_add_config_blob, 'umpire_config')
    self.assertEqual(
        test_add_config_blob,
        file_utils.ReadFile(os.path.join(self.umpire.resource_dir, conf)))

  def testValidateConfig(self):
    with self.assertRPCRaises('json.decoder.JSONDecodeError'):
      self.proxy.ValidateConfig('not a valid config.')

    with self.assertRPCRaises('KeyError'):
      self.proxy.ValidateConfig(
          self.ReadConfigTestdata('umpire_no_service.json'))

    with self.assertRPCRaises('SchemaInvalidException'):
      self.proxy.ValidateConfig(
          self.ReadConfigTestdata('umpire_wrong_schema.json'))

    with self.assertRPCRaises('Missing resource'):
      self.proxy.ValidateConfig(
          self.ReadConfigTestdata('umpire_missing_resource.json'))

  def testDeployConfig(self):
    to_deploy_config = self.ReadConfigTestdata('umpire_deploy.json')
    conf = self.proxy.AddConfigFromBlob(to_deploy_config, 'umpire_config')
    self.proxy.Deploy(conf)

    active_config = json.loads(self.proxy.GetActiveConfig())
    self.assertEqual(json.loads(to_deploy_config), active_config)

  def testDeployServiceConfigChanged(self):
    to_deploy_config = self.ReadConfigTestdata('umpire_deploy.json')
    conf = self.proxy.AddConfigFromBlob(to_deploy_config, 'umpire_config')
    self.proxy.Deploy(conf)

    to_deploy_config = self.ReadConfigTestdata(
        'umpire_deploy_service_config_changed.json')
    conf = self.proxy.AddConfigFromBlob(to_deploy_config, 'umpire_config')
    self.proxy.Deploy(conf)

    # TODO(pihsun): Figure out a better way to detect if services are restarted
    # without reading docker logs.
    docker_logs = process_utils.CheckOutput(
        ['docker', 'logs', self.umpire.container_name],
        stderr=subprocess.STDOUT).splitlines()
    restarted_services = []
    for log_line in reversed(docker_logs):
      if re.search(r'Config .* validated\. Try deploying', log_line):
        # Read logs until last deploy.
        break
      m = re.search(r'Service (.*) started: \[(.*)\]', log_line)
      if m is None:
        continue
      service = m.group(1)
      restarted = len(m.group(2)) > 0
      logging.debug('%s: restarted=%s', service, restarted)
      if restarted:
        restarted_services.append(service)
    # Assert that the only restarted service is instalog.
    self.assertEqual(['instalog'], restarted_services)

  def testDeployConfigFail(self):
    # You need a config with "unable to start some service" for this fail.
    to_deploy_config = self.ReadConfigTestdata('umpire_deploy_fail.json')
    conf = self.proxy.AddConfigFromBlob(to_deploy_config, 'umpire_config')
    with self.assertRPCRaises('Deploy failed'):
      self.proxy.Deploy(conf)

    active_config = json.loads(self.proxy.GetActiveConfig())
    self.assertEqual(self.default_config, active_config)

  def testStopStartService(self):
    test_rsync_cmd = (
        f'rsync rsync://localhost:{int(self.umpire.port + 4)}/system_logs '
        '>/dev/null 2>&1')

    self.proxy.StopServices(['rsync'])
    self.assertNotEqual(0, subprocess.call(test_rsync_cmd, shell=True))

    self.proxy.StartServices(['rsync'])
    subprocess.check_call(test_rsync_cmd, shell=True)

  def testAddPayload(self):
    payload = self.proxy.AddPayload('/mnt/hwid.gz', 'hwid')
    resource = payload['hwid']['file']
    resource_path = os.path.join(self.umpire.resource_dir, resource)

    self.assertRegex(resource, r'hwid\..*\.gz')
    with gzip.open(os.path.join(SHARED_TESTDATA_DIR, 'hwid.gz')) as f1:
      with gzip.open(resource_path) as f2:
        self.assertEqual(f1.read(), f2.read())

    os.unlink(resource_path)

  def testUpdate(self):
    payload = self.proxy.AddPayload('/mnt/hwid.gz', 'hwid')
    resource = payload['hwid']['file']
    self.proxy.Update([('hwid', os.path.join(DOCKER_RESOURCE_DIR, resource))])

    active_config = json.loads(self.proxy.GetActiveConfig())
    payload = self.proxy.GetPayloadsDict(
        active_config['bundles'][0]['payloads'])
    self.assertEqual(resource, payload['hwid']['file'])

    os.unlink(os.path.join(self.umpire.resource_dir, resource))

  def testImportBundle(self):
    resources = {
        'complete': 'complete.d41d8cd98f00b204e9800998ecf8427e.gz',
        'toolkit': 'toolkit.26a11b67b5abda74b4292cb84cedef26.gz',
        'firmware': 'firmware.7c5f73ab48d570fac54057ccf50eb28a.gz',
        'hwid': 'hwid.d173cfd28e47a0bf7f2760784f55580e.gz'
    }
    # TODO(pihsun): Add test data for test_image and release_image.

    self.proxy.ImportBundle('/mnt/bundle_for_import.zip', 'umpire_test')

    active_config = json.loads(self.proxy.GetActiveConfig())
    new_bundle = next(bundle for bundle in active_config['bundles']
                      if bundle['id'] == 'umpire_test')
    new_payload = self.proxy.GetPayloadsDict(new_bundle['payloads'])

    for resource_type, resource in resources.items():
      self.assertTrue(
          os.path.exists(os.path.join(self.umpire.resource_dir, resource)))
      self.assertEqual(new_payload[resource_type]['file'], resource)

    self.assertEqual('umpire_test', active_config['active_bundle_id'])
    for bundle in active_config['bundles']:
      if bundle['id'] == 'umpire_test':
        self.assertEqual('', bundle['note'])


class UmpireHTTPTest(UmpireDockerTestCase):
  """Tests for Umpire http features."""
  def setUp(self):
    super().setUp()
    self.proxy = xmlrpc.client.ServerProxy(self.umpire.rpc_addr_base)
    self.addCleanup(_CloseServerProxyConnection, self.proxy)

  def testReverseProxy(self):
    to_deploy_config = file_utils.ReadFile(
        os.path.join(CONFIG_TESTDATA_DIR, 'umpire_deploy_proxy.json'))
    conf = self.proxy.AddConfigFromBlob(to_deploy_config, 'umpire_config')
    self.proxy.Deploy(conf)

    response = requests.get(
        f'http://localhost:{int(self.umpire.port)}/res/test',
        allow_redirects=False)
    self.assertEqual(307, response.status_code)
    self.assertEqual('http://11.22.33.44/res/test',
                     response.headers['Location'])


class RPCDUTTest(UmpireDockerTestCase):
  """Tests for Umpire DUT RPC."""
  def setUp(self):
    super().setUp()
    self.proxy = xmlrpc.client.ServerProxy(self.umpire.addr_base)
    shutil.copy(
        os.path.join(CONFIG_TESTDATA_DIR, 'test_report_index.json'),
        os.path.join(self.umpire.umpire_dir, 'properties', 'report_index.json'))
    self.addCleanup(_CloseServerProxyConnection, self.proxy)

  def testPing(self):
    version = self.proxy.Ping()
    self.assertEqual({
        'version': 3,
        'project': self.umpire.project_name
    }, version)

  def testEndingSlashInProxyAddress(self):
    with xmlrpc.client.ServerProxy(self.umpire.addr_base) as proxy:
      self.assertEqual({
          'version': 3,
          'project': self.umpire.project_name
      }, proxy.Ping())

  def testGetTime(self):
    t = self.proxy.GetTime()
    self.assertAlmostEqual(t, time.time(), delta=1)

  def testAlternateURL(self):
    with xmlrpc.client.ServerProxy(f'{self.umpire.addr_base}/umpire') as proxy:
      version = proxy.Ping()
      self.assertEqual({
          'version': 3,
          'project': self.umpire.project_name
      }, version)

  def testGetFactoryLogPort(self):
    self.assertEqual(self.umpire.port + 4, self.proxy.GetFactoryLogPort())

  def _GenerateReportBlob(self):
    report_path = os.path.join(SHARED_TESTDATA_DIR, 'report_for_upload.rpt.xz')
    report_blob = file_utils.ReadFile(report_path, encoding=None)
    with tarfile.open(report_path, 'r:xz') as tar_file:
      file_list = tar_file.getnames()
    return report_blob, file_list

  def testUploadReport(self):
    report_blob, file_list = self._GenerateReportBlob()
    self.assertTrue(self.proxy.UploadReport('test_serial', report_blob))
    # Report uses GMT time
    timezone = None
    service_config = ServiceTest().ReadConfigTestdata(
        'umpire_timezone_service.json')['services']
    if 'umpire_timezone' in service_config:
      if service_config['umpire_timezone']['active']:
        timezone = service_config['umpire_timezone']['timezone']
    now = time_utils.GetNowWithTimezone(timezone)
    report_pattern = os.path.join(
        self.umpire.umpire_dir, 'umpire_data', 'report',
        time.strftime('%Y%m%d', now), 'Unknown-test_serial-*.rpt.xz')
    report_files = glob.glob(report_pattern)
    self.assertEqual(1, len(report_files))
    report_file = report_files[0]
    with tarfile.open(report_file, 'r:xz', ignore_zeros=True) as tar_file:
      self.assertEqual(tar_file.getnames(), file_list + ['metadata.json'])
      for tarinfo in tar_file.getmembers():
        if tarinfo.name == 'metadata.json':
          metadata_json = json_utils.LoadStr(
              tar_file.extractfile(tarinfo).read())
          self.assertEqual('0000000001', metadata_json['report_index'])


class ServiceTest(TwoUmpireDockerTestCase):

  def setUp(self):
    super().setUp()
    self.proxy = xmlrpc.client.ServerProxy(self.umpire.rpc_addr_base)
    self.second_proxy = xmlrpc.client.ServerProxy(
        self.second_umpire.rpc_addr_base)
    self.addCleanup(_CloseServerProxyConnection, self.proxy)
    self.addCleanup(_CloseServerProxyConnection, self.second_proxy)

  def ReadConfigTestdata(self, name):
    return json_utils.LoadFile(os.path.join(CONFIG_TESTDATA_DIR, name))

  def StartService(self, config, wait_time=0):
    conf = self.proxy.AddConfigFromBlob(
        json_utils.DumpStr(config), 'umpire_config')
    self.proxy.Deploy(conf)
    time.sleep(wait_time)

  def testSyncService(self):
    docker_bridge_gateway_ip = process_utils.CheckOutput([
        'docker', 'network', 'inspect', '--format',
        '{{(index .IPAM.Config 0).Gateway}}', 'bridge'
    ]).strip()
    # The secondary ip should be the ip of `docker0` gateway interface.
    to_deploy_config = self.ReadConfigTestdata('umpire_sync_service.json')
    to_deploy_config['services']['umpire_sync']['primary_information'] = {
        'ip': docker_bridge_gateway_ip,
        'port': str(self.umpire.port)
    }
    to_deploy_config['services']['umpire_sync']['secondary_information'][0] = {
        'ip': docker_bridge_gateway_ip,
        'port': str(self.second_umpire.port)
    }
    self.StartService(to_deploy_config, wait_time=2)
    self.assertEqual(self.proxy.GetActivePayload(),
                     self.second_proxy.GetActivePayload())
    second_url = (
        f'http://{docker_bridge_gateway_ip}:{int(self.second_umpire.port)}')
    self.assertEqual(self.proxy.GetUmpireSyncStatus()[second_url]['status'],
                     'Success')


if __name__ == '__main__':
  logging.getLogger().setLevel(int(os.environ.get('LOG_LEVEL') or logging.INFO))
  unittest.main()
