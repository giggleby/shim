#!/usr/bin/python
# -*- coding: utf-8 -*-
#
# Copyright (c) 2012 The Chromium OS Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

import cgi
import logging
import os
import threading
import traceback

from cros.factory.test import factory
from cros.factory.test.factory import TestState
from cros.factory.test.event import Event, EventClient


# For compatibility; moved to factory.
FactoryTestFailure = factory.FactoryTestFailure


# Import cgi.escape.
Escape = cgi.escape


def MakeLabel(en, zh=None, css_class=None):
  '''Returns a label which will appear in the active language.

  Args:
      en: The English-language label.
      zh: The Chinese-language label (or None if unspecified).
      css_class: The CSS class to decorate the label (or None if unspecified).
  '''
  return ('<span class="goofy-label-en %s">%s</span>'
          '<span class="goofy-label-zh %s">%s</span>' %
          ('' if css_class is None else css_class, en,
           '' if css_class is None else css_class, (en if zh is None else zh)))


def MakeTestLabel(test):
  '''Returns label for a test name in the active language.

  Args:
     test: A test object from the test list.
  '''
  return MakeLabel(Escape(test.label_en), Escape(test.label_zh))


def MakeStatusLabel(status):
  '''Returns label for a test status in the active language.

  Args:
      status: One of [PASSED, FAILED, ACTIVE, UNTESTED]
  '''
  STATUS_ZH = {
    TestState.PASSED: u'良好',
    TestState.FAILED: u'不良',
    TestState.ACTIVE: u'正在測',
    TestState.UNTESTED: u'未測'
  }
  return MakeLabel(status.lower(),
                   STATUS_ZH.get(status, status))


class UI(object):
  '''Web UI for a Goofy test.

  You can set your test up in the following ways:

  1. For simple tests with just Python+HTML+JS:

     mytest.py
     mytest.js  (automatically loaded)
     mytest.html (automatically loaded)

    This works for autotests too:

     factory_MyTest.py
     factory_MyTest.js  (automatically loaded)
     factory_MyTest.html (automatically loaded)

  2. If you have more files to include, like images
    or other JavaScript libraries:

     mytest.py
     mytest_static/
      mytest.js      (automatically loaded)
      mytest.html     (automatically loaded)
      some_js_library.js (NOT automatically loaded;
                use <script src="some_js_lib.js">)
      some_image.gif   (use <img src="some_image.gif">)

  3. Same as #2, but with a directory just called "static" instead of
    "mytest_static". This is nicer if your test is already in a
    directory that contains the test name (as for autotests). So
    for a test called factory_MyTest.py, you might have:

     factory_MyTest/
      factory_MyTest.py
      static/
       factory_MyTest.html (automatically loaded)
       factory_MyTest.js  (automatically loaded)
       some_js_library.js
       some_image.gif

  4. Some UI templates are available. Templates have several predefined
    sections like title, instruction, state. Hepler functions are
    provided in the template class to access different sections. See
    test/test_ui_templates.py for more information.

    Currently there are two templates available:
      - ui_templates.OneSection
      - ui_templates.TwoSections


  Note that if you rename .html or .js files during development, you
  may need to restart the server for your changes to take effect.
  '''
  def __init__(self, css=None):
    self.lock = threading.RLock()
    self.event_client = EventClient(callback=self._HandleEvent)
    self.test = os.environ['CROS_FACTORY_TEST_PATH']
    self.invocation = os.environ['CROS_FACTORY_TEST_INVOCATION']
    self.event_handlers = {}

    self._SetupStaticFiles(os.path.realpath(traceback.extract_stack()[-2][0]))
    self.error_msgs = []
    if css:
      self.AppendCSS(css)

  def _SetupStaticFiles(self, py_script):
    # Get path to caller and register static files/directories.
    base = os.path.splitext(py_script)[0]

    # Directories we'll autoload .html and .js files from.
    autoload_bases = [base]

    # Find and register the static directory, if any.
    static_dirs = filter(os.path.exists,
                         [base + '_static',
                          os.path.join(os.path.dirname(py_script), 'static')
                         ])
    if len(static_dirs) > 1:
      raise FactoryTestFailure('Cannot have both of %s - delete one!' %
                               static_dirs)
    if static_dirs:
      factory.get_state_instance().register_path(
          '/tests/%s' % self.test, static_dirs[0])
      autoload_bases.append(
          os.path.join(static_dirs[0], os.path.basename(base)))

    def GetAutoload(extension):
      autoload = filter(os.path.exists,
                        [x + '.' + extension
                         for x in autoload_bases])
      if not autoload:
        return ''
      if len(autoload) > 1:
        raise FactoryTestFailure(
            'Cannot have both of %s - delete one!' %
            autoload)

      factory.get_state_instance().register_path(
        '/tests/%s/%s' % (self.test, os.path.basename(autoload[0])),
        autoload[0])
      return open(autoload[0]).read()

    html = '\n'.join(
      ['<head id="head">',
       '<base href="/tests/%s/">' % self.test,
       '<link rel="stylesheet" type="text/css" href="/goofy.css">',
       '<link rel="stylesheet" type="text/css" href="/test.css">',
       GetAutoload('html')])
    self.PostEvent(Event(Event.Type.INIT_TEST_UI, html=html))

    js = GetAutoload('js')
    if js:
      self.RunJS(js)

  def SetHTML(self, html, append=False, id=None):  # pylint: disable=W0622
    '''Sets the UI in the test pane.

    Note that <script> tags are not allowed in SetHTML() and
    AppendHTML(), since the scripts will not be executed. Use RunJS()
    or CallJSFunction() instead.

    Args:
      id: If given, writes html to the element identified by id.
    '''
    self.PostEvent(Event(Event.Type.SET_HTML, html=html, append=append, id=id))

  def AppendHTML(self, html, **kwargs):
    '''Append to the UI in the test pane.'''
    self.SetHTML(html, True, **kwargs)

  def AppendCSS(self, css):
    '''Append CSS in the test pane.'''
    self.AppendHTML('<style type="text/css">%s</style>' % css,
                    id="head")

  def RunJS(self, js, **kwargs):
    '''Runs JavaScript code in the UI.

    Args:
      js: The JavaScript code to execute.
      kwargs: Arguments to pass to the code; they will be
        available in an "args" dict within the evaluation
        context.

    Example:
      ui.RunJS('alert(args.msg)', msg='The British are coming')
    '''
    self.PostEvent(Event(Event.Type.RUN_JS, js=js, args=kwargs))

  def CallJSFunction(self, name, *args):
    '''Calls a JavaScript function in the test pane.

    This will be run within window scope (i.e., 'this' will be the
    test pane window).

    Args:
      name: The name of the function to execute.
      args: Arguments to the function.
    '''
    self.PostEvent(Event(Event.Type.CALL_JS_FUNCTION, name=name, args=args))

  def AddEventHandler(self, subtype, handler):
    '''Adds an event handler.

    Args:
      subtype: The test-specific type of event to be handled.
      handler: The handler to invoke with a single argument (the event
        object).
    '''
    self.event_handlers.setdefault(subtype, []).append(handler)

  def PostEvent(self, event):
    '''Posts an event to the event queue.

    Adds the test and invocation properties.

    Tests should use this instead of invoking post_event directly.'''
    event.test = self.test
    event.invocation = self.invocation
    self.event_client.post_event(event)

  def URLForFile(self, path):
    '''Returns a URL that can be used to serve a local file.

    Args:
      path: path to the local file

    Returns:
      url: A (possibly relative) URL that refers to the file
    '''
    return factory.get_state_instance().URLForFile(path)

  def URLForData(self, mime_type, data, expiration=None):
    '''Returns a URL that can be used to serve a static collection
    of bytes.

    Args:
      mime_type: MIME type for the data
      data: Data to serve
      expiration_secs: If not None, the number of seconds in which
      the data will expire.
    '''
    return factory.get_state_instance().URLForData(
        mime_type, data, expiration)

  def Pass(self):
    '''Passes the test.'''
    self.PostEvent(Event(Event.Type.END_TEST, status=TestState.PASSED))

  def Fail(self, error_msg):
    '''Fails the test immediately.'''
    self.PostEvent(Event(Event.Type.END_TEST, status=TestState.FAILED,
                         error_msg=error_msg))

  def FailLater(self, error_msg):
    '''Appends a error message to the error message list, which causes
    the test to fail later.
    '''
    self.error_msgs.append(error_msg)

  def EnablePassFailKeys(self):
    '''Allows space/enter to pass the test, and escape to fail it.'''
    self.RunJS('window.test.enablePassFailKeys()')

  def Run(self):
    '''Runs the test UI, waiting until the test completes.'''
    event = self.event_client.wait(
        lambda event:
          (event.type == Event.Type.END_TEST and
           event.invocation == self.invocation and
           event.test == self.test))
    logging.info('Received end test event %r', event)
    self.event_client.close()

    if event.status == TestState.PASSED and not self.error_msgs:
      pass
    elif event.status == TestState.FAILED or self.error_msgs:
      error_msg = getattr(event, 'error_msg', '')
      if self.error_msgs:
        error_msg += ('\n'.join([''] + self.error_msgs))

      raise FactoryTestFailure(error_msg)
    else:
      raise ValueError('Unexpected status in event %r' % event)

  def _HandleEvent(self, event):
    '''Handles an event sent by a test UI.'''
    if (event.type == Event.Type.TEST_UI_EVENT and
        event.test == self.test and
        event.invocation == self.invocation):
      with self.lock:
        for handler in self.event_handlers.get(event.subtype, []):
          handler(event)
