#!/usr/bin/env python3
#
# Copyright 2017 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

import os
import time
import unittest
import urllib.error
import urllib.request

from jsonrpclib import jsonrpc

from cros.factory.goofy import goofy_server
from cros.factory.utils import file_utils
from cros.factory.utils import net_utils
from cros.factory.utils import process_utils
from cros.factory.utils import sync_utils


class PathResolverTest(unittest.TestCase):

  def _Callback(self):
    pass

  def testWithRoot(self):
    resolver = goofy_server.PathResolver()
    resolver.AddPath('/', '/root')
    resolver.AddPath('/a/b', '/c/d')
    resolver.AddPath('/a', '/e')
    resolver.AddHandler('/callback', self._Callback)

    for url_path, expected in (
        ('/', '/root'),
        ('/a/b', '/c/d'),
        ('/a', '/e'),
        ('/a/b/X', '/c/d/X'),
        ('/a/X', '/e/X'),
        ('/X', '/root/X'),
        ('/X/', '/root/X/'),
        ('/X/Y', '/root/X/Y'),
        ('Blah', None),
        ('/callback', self._Callback)):
      self.assertEqual(expected,
                       resolver.Resolve(url_path))

  def testNoRoot(self):
    resolver = goofy_server.PathResolver()
    resolver.AddPath('/a/b', '/c/d')
    self.assertEqual(None, resolver.Resolve('/b'))
    self.assertEqual('/c/d/X', resolver.Resolve('/a/b/X'))

  def testRootHandler(self):
    resolver = goofy_server.PathResolver()
    resolver.AddHandler('/', self._Callback)
    resolver.AddPath('/a', '/e')

    self.assertEqual(resolver.Resolve('/'), self._Callback)
    self.assertEqual(resolver.Resolve('/a/b'), '/e/b')
    self.assertEqual(resolver.Resolve('/b'), None)


class GoofyServerTest(unittest.TestCase):

  def setUp(self):
    def ServerReady():
      try:
        with urllib.request.urlopen(
            f"http://{net_utils.LOCALHOST}:{int(self.port)}{'/not_exists'}"):
          pass
      except urllib.error.HTTPError as err:
        if err.code == 404:
          return True
      return False

    self.port = net_utils.FindUnusedTCPPort()
    self.server = goofy_server.GoofyServer(
        (net_utils.LOCALHOST, self.port))
    self.server_thread = process_utils.StartDaemonThread(
        target=self.server.serve_forever,
        args=(0.01,),
        name='GoofyServer')

    # Wait for server to start.
    sync_utils.WaitFor(ServerReady, 0.1)

  def testAddRPCInstance(self):
    class RPCInstance:
      def __init__(self):
        self.called = False

      def Func(self):
        self.called = True

    instance = RPCInstance()
    self.server.AddRPCInstance('/test', instance)

    proxy = jsonrpc.ServerProxy(
        f'http://{net_utils.LOCALHOST}:{int(self.port)}/test')
    proxy.Func()
    self.assertTrue(instance.called)

  def testAddHTTPGetHandler(self):
    data = b'<html><body><h1>Hello</h1></body></html>'
    mime_type = 'text/html'

    def MyHandler(handler):
      handler.send_response(200)
      handler.send_header('Content-Type', mime_type)
      handler.send_header('Content-Length', len(data))
      handler.end_headers()
      handler.wfile.write(data)

    self.server.AddHTTPGetHandler('/test', MyHandler)

    with urllib.request.urlopen(
        f'http://{net_utils.LOCALHOST}:{int(self.port)}/test') as response:
      self.assertEqual(200, response.getcode())
      self.assertEqual(data, response.read())

  def testRegisterPath(self):
    data = b'<html><body><h1>Hello</h1></body></html>'
    with file_utils.TempDirectory() as path:
      with open(os.path.join(path, 'index.html'), 'wb') as f:
        f.write(data)

      self.server.RegisterPath('/', path)
      with urllib.request.urlopen(
          f'http://{net_utils.LOCALHOST}:{int(self.port)}/') as response:
        self.assertEqual(200, response.getcode())
        self.assertEqual(data, response.read())

      # Check svg mime type
      with open(os.path.join(path, 'test.svg'), 'wb') as f:
        f.write(data)
      with urllib.request.urlopen(
          f'http://{net_utils.LOCALHOST}:{int(self.port)}/test.svg'
      ) as response:
        self.assertEqual(200, response.getcode())
        self.assertEqual(data, response.read())

  def testURLForData(self):
    data = b'<html><body><h1>Hello</h1></body></html>'

    url = self.server.URLForData('text/html', data)

    with urllib.request.urlopen(
        f'http://{net_utils.LOCALHOST}:{int(self.port)}{url}') as response:
      self.assertEqual(200, response.getcode())
      self.assertEqual(data, response.read())

  def testRegisterData(self):
    data = b'<html><body><h1>Hello</h1></body></html>'

    url = '/some/page.html'
    self.server.RegisterData(url, 'text/html', data)

    with urllib.request.urlopen(
        f'http://{net_utils.LOCALHOST}:{int(self.port)}{url}') as response:
      self.assertEqual(200, response.getcode())
      self.assertEqual(data, response.read())

  def testRegisterDataUnicode(self):
    data = u'<html><body><h1>Hello\u4e16\u754c</h1></body></html>'

    url = '/some/page.html'
    self.server.RegisterData(url, 'text/html', data)

    with urllib.request.urlopen(
        f'http://{net_utils.LOCALHOST}:{int(self.port)}{url}') as response:
      self.assertEqual(200, response.getcode())
      self.assertEqual(data, response.read().decode('UTF-8'))

  def testGoofyServerRPC(self):
    proxy = jsonrpc.ServerProxy(
        f'http://{net_utils.LOCALHOST}:{int(self.port)}/')
    self.assertCountEqual(
        ['URLForData',
         'URLForFile',
         'RegisterPath',
         'system.listMethods',
         'system.methodHelp',
         'system.methodSignature'],
        proxy.system.listMethods())

    data = '<html><body><h1>Hello</h1></body></html>'
    url = proxy.URLForData('text/html', data)
    with urllib.request.urlopen(
        f'http://{net_utils.LOCALHOST}:{int(self.port)}{url}') as response:
      self.assertEqual(200, response.getcode())
      self.assertEqual(data, response.read().decode('utf-8'))

  def testURLForFile(self):
    data = '<html><body><h1>Hello</h1></body></html>'
    with file_utils.UnopenedTemporaryFile() as path:
      file_utils.WriteFile(path, data)

      url = self.server.URLForFile(path)
      with urllib.request.urlopen(
          f'http://{net_utils.LOCALHOST}:{int(self.port)}{url}') as response:
        self.assertEqual(200, response.getcode())
        self.assertEqual(data, response.read().decode('utf-8'))

  def testURLForDataExpire(self):
    data = '<html><body><h1>Hello</h1></body></html>'

    url = self.server.URLForData('text/html', data, 0.8)

    with urllib.request.urlopen(
        f'http://{net_utils.LOCALHOST}:{int(self.port)}{url}') as response:
      self.assertEqual(200, response.getcode())
      self.assertEqual(data, response.read().decode('utf-8'))

    time.sleep(1)

    # The data should expired now.
    with self.assertRaises(urllib.error.HTTPError):
      with urllib.request.urlopen(
          f'http://{net_utils.LOCALHOST}:{int(self.port)}{url}'):
        pass

  def testURLNotFound(self):
    with self.assertRaisesRegex(urllib.error.HTTPError, '404: Not Found'):
      with urllib.request.urlopen(
          f"http://{net_utils.LOCALHOST}:{int(self.port)}{'/not_exists'}"):
        pass

  def tearDown(self):
    self.server.shutdown()
    self.server_thread.join()
    self.server.server_close()


if __name__ == '__main__':
  unittest.main()
