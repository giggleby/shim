#!/usr/bin/env python3
#
# Copyright 2018 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.


"""Generates some .rst files used to document parts of the factory toolkit.

Currently this generates a list of all available pytests, in the
doc/pytests directory.  In the future it may be extended to generate,
for example, a test list tree.

(Ideally these could be generated via Sphinx extensions, but this is not
always practical.)
"""


import argparse
import codecs
import inspect
from io import StringIO
import logging
import os
import re
from typing import Any, Dict, List, Union

from cros.factory.probe import function as probe_function
from cros.factory.test.env import paths
from cros.factory.test.test_lists import manager
from cros.factory.test.test_lists import test_object as test_object_module
from cros.factory.test.utils import pytest_utils
from cros.factory.utils import file_utils
from cros.factory.utils import json_utils
from cros.factory.utils.type_utils import Enum


DOC_GENERATORS = {}
SRC_URL_BASE = ("https://chromium.googlesource.com/chromiumos/platform/factory/"
                "+/refs/heads/main/py/test/pytests/")


def DocGenerator(dir_name):
  def Decorator(func):
    assert dir_name not in DOC_GENERATORS
    DOC_GENERATORS[dir_name] = func
    return func

  return Decorator


def Escape(text):
  r"""Escapes characters that must be escaped in a raw tag (*, `, and \)."""
  return re.sub(r'([*`\\])', '\\\\\\1', text)


def Indent(text, prefix, first_line_prefix=None):
  """Indents a string.

  Args:
    text: The input string.
    prefix: The string to insert at the beginning of each line.
    first_line_prefix: The string to insert at the beginning of the first line.
        Defaults to prefix if unspecified.
  """
  if first_line_prefix is None:
    first_line_prefix = prefix

  return re.sub(
      '(?m)^',
      lambda match: first_line_prefix if match.start() == 0 else prefix,
      text)


def LinkToDoc(name, path):
  """Create a hyper-link tag which links to another document file.

  Args:
    name: The tag name.
    path: Path of the target document, either absolute or relative.
  """
  return f':doc:`{Escape(name)} <{Escape(path)}>`'


def LinkToCode(pytest_name):
  """Create a hyper-link to the source code to pytest.

  Args:
    pytest_name: The pytest name.
  """
  pytest_path = '/'.join(pytest_name.split('.')) + '.py'
  source_url = os.path.join(SRC_URL_BASE, pytest_path)
  return f'**Source code:** `{pytest_path} <{source_url}>`_'


class RSTWriter:
  def __init__(self, io):
    self.io = io

  def WriteTitle(self, title, mark, ref_label=None):
    if ref_label:
      self.io.write(f'.. _{Escape(ref_label)}:\n\n')
    self.io.write(title + '\n')
    self.io.write(mark * len(title) + '\n')

  def WriteParagraph(self, text):
    self.io.write(text + '\n\n')

  def WriteListItem(self, content):
    self.WriteParagraph('- ' + content)

  def WriteListTableHeader(self, widths=None, header_rows=None):
    self.io.write('.. list-table::\n')
    if widths is not None:
      self.io.write(f"   :widths: {' '.join(map(str, widths))}\n")
    if header_rows is not None:
      self.io.write(f'   :header-rows: {int(header_rows)}\n')
    self.io.write('\n')

  def WriteListTableRow(self, row):
    for i, cell in enumerate(row):
      # Indent the first line with " - " (or " * - " if it's the first
      # column)
      self.io.write(Indent(cell, ' ' * 7, '   * - ' if i == 0 else '     - '))
      self.io.write('\n')
    self.io.write('\n')


def WriteArgsTable(rst, title, args):
  """Writes a table describing arguments.

  Args:
    rst: An instance of RSTWriter for writting RST context.
    title: The title of the arguments section.
    args: A list of Arg objects, as in the ARGS attribute of a pytest.
  """
  rst.WriteTitle(title, '-')

  if not args:
    rst.WriteParagraph('This test does not have any arguments.')
    return

  rst.WriteListTableHeader(widths=(20, 10, 60), header_rows=1)
  rst.WriteListTableRow(('Name', 'Type', 'Description'))

  for arg in args:
    description = arg.help.strip()

    annotations = []
    if arg.IsOptional():
      annotations.append('optional')
      annotations.append(f'default: ``{Escape(repr(arg.default))}``')
    if annotations:
      description = f"({'; '.join(annotations)}) {description}"

    def FormatArgType(arg_type):
      if isinstance(arg_type, Enum):
        return repr(sorted(arg_type))
      if arg_type == type(None):
        return 'None'
      return arg_type.__name__
    arg_types = ', '.join(FormatArgType(x) for x in arg.type)

    rst.WriteListTableRow((arg.name, arg_types, description))


def GenerateTestDocs(rst, pytest_name):
  """Generates test docs for a pytest.

  Args:
    rst: A stream to write to.
    pytest_name: The name of pytest under package cros.factory.test.pytests.

  Returns:
    The first line of the docstring.
  """
  module = pytest_utils.LoadPytestModule(pytest_name)
  test_case = pytest_utils.FindTestCase(module)

  args = getattr(test_case, 'ARGS', [])

  doc = getattr(module, '__doc__', None)
  if doc is None:
    doc = f'No test-level description available for pytest {pytest_name}.'

  rst.WriteTitle(pytest_name, '=')
  rst.WriteParagraph(LinkToCode(pytest_name))
  rst.WriteParagraph(doc)
  WriteArgsTable(rst, 'Test Arguments', args)

  # Remove everything after the first pair of newlines.
  return re.sub(r'(?s)\n\s*\n.+', '', doc).strip()


@DocGenerator('pytests')
def GeneratePyTestsDoc(pytests_output_dir):
  # Map of pytest name to info returned by GenerateTestDocs.
  pytest_info = {}

  for relpath in pytest_utils.GetPytestList(paths.FACTORY_DIR):
    pytest_name = pytest_utils.RelpathToPytestName(relpath)
    with codecs.open(
        os.path.join(pytests_output_dir, pytest_name + '.rst'),
        'w', 'utf-8') as out:
      try:
        pytest_info[pytest_name] = GenerateTestDocs(RSTWriter(out), pytest_name)
      except Exception:
        logging.exception('Failed to generate document for pytest %s.',
                          pytest_name)

  index_rst = os.path.join(pytests_output_dir, 'index.rst')
  with open(index_rst, 'a', encoding='utf8') as f:
    rst = RSTWriter(f)
    for k, v in sorted(pytest_info.items()):
      rst.WriteListTableRow((LinkToDoc(k, k), v))


def WriteTestObjectDetail(
    rst: RSTWriter,
    documented_test_object_names: List[str],
    test_object_name: str,
    raw_test_object: Dict[str, Any],
    test: Union[test_object_module.FactoryTest, list],
) -> None:
  """Writes a test_object to output stream.

  Args:
    rst: An instance of RSTWriter for writing RST context.
    documented_test_object_names: The names of test objects that we have doc.
    test_object_name: The name of the test object.
    raw_test_object: a test_object defined by JSON test list without resolving
      inheritance.
    test: The resolved object from test_list.MakeTest. May be a list if it's a
      FlattenGroup.
  """
  rst.WriteTitle(Escape(test_object_name), '-')

  if '__comment' in raw_test_object:
    rst.WriteParagraph(Escape(raw_test_object['__comment']))

  if isinstance(test, test_object_module.FactoryTest) and test.run_if:
    rst.WriteTitle('run_if', '`')
    rst.WriteParagraph('::\n\n' + Indent(test.run_if, '  '))

  if isinstance(test, test_object_module.FactoryTest) and test.pytest_name:
    doc_path = os.path.join('..', 'pytests', test.pytest_name)
    rst.WriteTitle('pytest_name', '`')
    rst.WriteParagraph(LinkToDoc(test.pytest_name, doc_path))

  args = raw_test_object.get('args')
  if args:
    rst.WriteTitle('args', '`')
    for key, value in args.items():
      formatted_value = json_utils.DumpStr(value, pretty=True)
      formatted_value = '::\n\n' + Indent(formatted_value, '  ')
      formatted_value = Indent(formatted_value, '  ')
      rst.WriteParagraph(f'``{key}``\n{formatted_value}')

  subtests = raw_test_object.get('subtests')
  if subtests:
    rst.WriteTitle('subtests', '`')
    for value in subtests:
      if isinstance(value, str):
        formatted_value = value
        if value in documented_test_object_names:
          formatted_value = f'`{Escape(value)}`_'
        rst.WriteParagraph(f'- {formatted_value}\n')
      else:
        formatted_value = json_utils.DumpStr(value, pretty=True)
        formatted_value = '::\n\n' + Indent(formatted_value, '  ')
        formatted_value = Indent(formatted_value, '  ')
        rst.WriteParagraph(f'-{formatted_value}\n')

@DocGenerator('test_lists')
def GenerateTestListDoc(output_dir):
  manager_ = manager.Manager()
  manager_.BuildAllTestLists()

  for test_list_id in manager_.GetTestListIDs():
    out_path = os.path.join(output_dir, test_list_id + '.test_list.rst')

    with open(out_path, 'w', encoding='utf8') as out:
      rst = RSTWriter(out)

      logging.warning('processing test list %s', test_list_id)
      test_list = manager_.GetTestListByID(test_list_id)
      config = test_list.ToTestListConfig()
      raw_config = manager_.loader.Load(test_list_id, allow_inherit=False)

      rst.WriteTitle(test_list_id, '=')

      if raw_config.get('__comment'):
        rst.WriteParagraph(Escape(raw_config['__comment']))

      rst.WriteTitle('Inherit', '-')
      for parent in raw_config.get('inherit', []):
        rst.WriteListItem(LinkToDoc(parent, parent))

      rst_pytest_detail = RSTWriter(StringIO())
      has_pytest_detail = False

      rst_group_detail = RSTWriter(StringIO())
      has_group_detail = False

      test_object_names = sorted(raw_config['definitions'])
      cache = {}
      for test_object_name in test_object_names:
        resolved_test_object = config['definitions'][test_object_name]
        raw_test_object = test_list.ResolveTestObject(
            resolved_test_object, test_object_name, cache={})

        try:
          test = test_list.MakeTest(resolved_test_object, cache=cache)
        except Exception as err:
          raise ValueError(test_list_id) from err

        if (isinstance(test, test_object_module.FactoryTest) and
            test.pytest_name):
          has_pytest_detail = True
          WriteTestObjectDetail(rst_pytest_detail, test_object_names,
                                test_object_name, raw_test_object, test)
        elif isinstance(test, (test_object_module.FactoryTest, list)):
          has_group_detail = True
          WriteTestObjectDetail(rst_group_detail, test_object_names,
                                test_object_name, raw_test_object, test)
        else:
          logging.warning('Test Object %r with unknown type %r',
                          test_object_name, type(test))

      if has_pytest_detail:
        rst.WriteParagraph(rst_pytest_detail.io.getvalue())

      if has_group_detail:
        rst.WriteParagraph(rst_group_detail.io.getvalue())


def FinishTemplate(path, **kwargs):
  template = file_utils.ReadFile(path)
  file_utils.WriteFile(path, template.format(**kwargs))


def GetModuleClassDoc(cls):
  # Remove the indent.
  s = re.sub(r'^  ', '', cls.__doc__ or '', flags=re.M)

  return tuple(t.strip('\n')
               for t in re.split(r'\n\s*\n', s + '\n\n', maxsplit=1))


def GenerateProbeFunctionDoc(functions_path, func_name, func_cls):
  short_desc, main_desc = GetModuleClassDoc(func_cls)

  with open(
      os.path.join(functions_path, func_name + '.rst'), 'w',
      encoding='utf8') as f:
    rst = RSTWriter(f)
    rst.WriteTitle(func_name, '=')
    rst.WriteParagraph(short_desc)
    WriteArgsTable(rst, 'Function Arguments', func_cls.ARGS)
    rst.WriteParagraph(main_desc)

  return short_desc, os.path.join(os.path.basename(functions_path), func_name)


@DocGenerator('probe')
def GenerateProbeDoc(output_dir):
  func_tables = {}
  def _AppendToFunctionTable(func_cls, row):
    all_base_cls = inspect.getmro(func_cls)
    base_cls_index = all_base_cls.index(probe_function.Function) - 1
    if base_cls_index == 0:
      func_type = 'Misc'
      type_desc = ''
    else:
      func_type = all_base_cls[base_cls_index].__name__
      type_desc = GetModuleClassDoc(all_base_cls[base_cls_index])[1]

    if func_type not in func_tables:
      rst = func_tables[func_type] = RSTWriter(StringIO())
      rst.WriteTitle(func_type, '`', ref_label=func_type)
      rst.WriteParagraph(type_desc)
      rst.WriteListTableHeader(header_rows=1)
      rst.WriteListTableRow(('Function Name', 'Short Description'))

    func_tables[func_type].WriteListTableRow(row)

  functions_path = os.path.join(output_dir, 'functions')
  file_utils.TryMakeDirs(functions_path)

  # Parse all functions.
  probe_function.LoadFunctions()
  for func_name in sorted(probe_function.GetRegisteredFunctions()):
    func_cls = probe_function.GetFunctionClass(func_name)

    short_desc, doc_path = GenerateProbeFunctionDoc(
        functions_path, func_name, func_cls)
    _AppendToFunctionTable(
        func_cls, (LinkToDoc(func_name, doc_path), short_desc))

  # Generate list tables of all functions, category by the function type.
  functions_section_rst = RSTWriter(StringIO())

  # Always render `Misc` section at the end.
  func_types = sorted(func_tables.keys())
  if 'Misc' in func_types:
    func_types.remove('Misc')
    func_types.append('Misc')

  for func_type in func_types:
    func_table_rst = func_tables[func_type]
    functions_section_rst.WriteParagraph(func_table_rst.io.getvalue())

  # Generate the index file.
  FinishTemplate(os.path.join(output_dir, 'index.rst'),
                 functions_section=functions_section_rst.io.getvalue())


def main():
  parser = argparse.ArgumentParser(
      description='Generate .rst files for the factory toolkit')
  parser.add_argument('--output-dir', '-o',
                      help='Output directory (default: %default)', default='.')
  args = parser.parse_args()

  for dir_name, func in DOC_GENERATORS.items():
    full_path = os.path.join(args.output_dir, dir_name)
    file_utils.TryMakeDirs(full_path)
    func(full_path)


if __name__ == '__main__':
  main()
