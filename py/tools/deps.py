#!/usr/bin/env python3
# Copyright 2014 The Chromium OS Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""A simple python dependency checker.

Scans given python modules and see their dependency. Usage:
  deps.py PYTHON_FILE(s)...
"""

import argparse
import ast
from distutils import sysconfig
import functools
import importlib.util
import json
import multiprocessing
import os
import os.path
import re
import subprocess
import sys
from typing import NamedTuple, Optional, Sequence

import yaml

# Constants for config file.
CONFIG_GROUPS = r'groups'
CONFIG_RULES = r'rules'
CONFIG_GROUP_PATTERN = re.compile(r'^<([^<>].*)>$')


FACTORY_DIR = os.path.abspath(os.path.join(__file__, '..', '..', '..'))
PY_BASE_DIR = os.path.join(FACTORY_DIR, 'py')
PY_PKG_BASE_DIR = os.path.join(FACTORY_DIR, 'py_pkg', 'cros', 'factory')
PY_PKG_ROOT_DIR = os.path.join(FACTORY_DIR, 'py_pkg')

STANDARD_LIB_DIR = sysconfig.get_python_lib(standard_lib=True) + '/'
SITE_PACKAGES_DIR = sysconfig.get_python_lib(standard_lib=False) + '/'

_KNOWN_STD_LIB_EXCEPTIONS = frozenset(['zipimport'])


class ImportCollector(ast.NodeVisitor):
  """An ast.NodeVisitor that would collect all import statements in a file.

  To support conditional dependency, the imports in a try-catch block with
  ImportError catched would not be collected.
  """
  def __init__(self):
    self.import_list = []
    self.try_import_block_count = 0

  def visit_Import(self, node):
    """Visiting a 'import xxx.yyy' statement"""
    if self.try_import_block_count:
      return
    for alias in node.names:
      self.import_list.append({
          'module': alias.name,
          'level': 0,
          'import': None
      })

  def visit_ImportFrom(self, node):
    """Visiting a 'from xxx.yyy import zzz' statement"""
    if self.try_import_block_count:
      return
    for alias in node.names:
      self.import_list.append({
          'module': node.module or '',
          'level': node.level,
          'import': alias.name
      })

  def visit_Try(self, node):
    if any(
        isinstance(x.type, ast.Name) and x.type.id == 'ImportError'
        for x in node.handlers):
      # We're in a try: ...; except ImportError: ... block, assume that this is
      # a conditional import, and don't add things inside to import list.
      self.try_import_block_count += 1
      self.generic_visit(node)
      self.try_import_block_count -= 1
    else:
      self.generic_visit(node)


def ReconstructSourceImport(item):
  """Reconstruct the original import line from values in ImportCollector.

  This is used to output human-friendly error message.
  """
  if item['import'] is None:
    return "import %s" % item['module']
  module = ''.join(['.'] * item['level'])
  module += item['module'] or ''
  return "from %s import %s" % (module, item['import'])


def GuessModule(filename):
  """Guess the module name from Python file name."""
  for base in [PY_BASE_DIR, PY_PKG_BASE_DIR]:
    if filename.startswith(base + '/'):
      relpath = filename[len(base) + 1:]
      subpaths = os.path.splitext(relpath)[0].split('/')
      if subpaths[-1] == '__init__':
        subpaths.pop()
      return 'cros.factory.' + '.'.join(subpaths)
  return None


class _ModuleSpec(NamedTuple):
  is_builtin: bool
  origin: Optional[str] = None
  submodule_search_locations: Optional[Sequence[str]] = None


def FindModuleSpec(name, paths) -> Optional[_ModuleSpec]:
  """Wrapper for importlib.util.find_spec, that returns the module spec."""

  if name in sys.builtin_module_names:
    # (Python 3.6) There are exceptions where some modules in
    # sys.builtin_module_names but the origin of module spec is empty.  (e.g.
    # sys, _imp, builtins).  Therefore we don't use spec.origin == 'built-in' as
    # the builtin check.
    return _ModuleSpec(True)

  # importlib.util.find_spec supports recursively import for multi-level modules
  # like x.y.z while importlib.machineary.PathFinder.find_spec does not.
  # However, importlib.util.find_spec does not support custom paths to search
  # modules, and we have to temporarily modify sys.path to make the lookup work.
  old_sys_path = list(sys.path)
  sys.path = paths
  try:
    try:
      spec = importlib.util.find_spec(name)
    except ModuleNotFoundError:
      # Raised when trying to find spec for x.y but cannot find the
      # module/package x.
      # e.g. importlib.util.find_spec('nosuchpackage.module')
      return None
    if spec is None:
      # Cannot get the spec of this module from given paths.
      # e.g. importlib.util.find_spec('nosuchpackageormodule')
      return None
    origin = spec.origin
    if spec.submodule_search_locations:  # The name is a package.
      if not origin:
        # Python 3.9 does not set origin = 'namespace' for namespace packages.
        origin = 'namespace'
      return _ModuleSpec(False, origin, list(spec.submodule_search_locations))
    # The name is a module.
    return _ModuleSpec(False, origin)
  finally:
    sys.path = old_sys_path


def GuessIsBuiltinOrStdlib(module):
  """Guess if a module is builtin or standard lib module for Python.

  A module is a builtin module for Python if the module name is in
  sys.builtin_module_names.  For standard library check, the origin of the
  module spec should be under standard library directory but not under site
  packages directory.
  """
  top_module = module.partition('.')[0]
  if top_module in _KNOWN_STD_LIB_EXCEPTIONS:
    # e.g. (Python3.8) The origin of 'zipimport' module spec is set to 'frozen'
    # which we could not determine if it's a stdlib or not.
    return True

  module_spec = FindModuleSpec(top_module, sys.path)
  if module_spec is None:  # Cannot import this module from sys.path
    return False
  if module_spec.is_builtin:
    return True
  # TODO: The stdlib check could be replaced with sys.stdlib_module_names check
  # in Python 3.10.

  # On some environment, the origin might be set as relative paths like
  # /usr/lib/python-exec/python3.6/../../../lib64/python3.6/os.py, so we have to
  # normalize it first.
  origin = os.path.normpath(module_spec.origin)
  return origin.startswith(
      STANDARD_LIB_DIR) and not origin.startswith(SITE_PACKAGES_DIR)


def GetSysPathInDir(file_dir, additional_script=''):
  """Opens a subprocess to get the sys.path in a directory.

  If additional_script is given, it'll be run inside the subprocess.
  """
  return json.loads(
      subprocess.check_output(
          [
              'python3', '-c', (
                  'import sys\n'
                  'import os\n'
                  'import json\n'
                  '%s\n'
                  'print(json.dumps([os.path.abspath(p) for p in sys.path]))') %
              additional_script
          ],
          cwd=file_dir))


def GetImportList(filename, module_name):
  """Get a list of imported modules of the file."""
  file_dir = os.path.dirname(filename)
  current_sys_path = GetSysPathInDir(file_dir)
  current_sys_path.append(PY_PKG_ROOT_DIR)
  import_list = []

  with open(filename, 'r', encoding='utf8') as fin:
    source = fin.read()

  root = ast.parse(source, filename)
  collector = ImportCollector()
  collector.visit(root)

  for item in collector.import_list:
    module = item['module']
    import_item = item['import']

    if import_item is None:
      # import xxx.yyy

      # Although import a.b.c brings a, a.b, a.b.c into namespace, we assume
      # that the code meant to only depends on a.b.c.
      import_list.append(module)
    else:
      # from x.y.z import foo
      # Try to import x.y.z to see if foo is a method or a module.

      # Resolve relative packages.
      final_module = importlib.util.resolve_name('.' * item['level'] + module,
                                                 module_name.rpartition('.')[0])

      module_spec = FindModuleSpec(final_module, current_sys_path)
      if module_spec is None:
        # if import failed at any point, make some educated guess on whether
        # the last part is a module or method.
        # This can happen for external library dependency.
        # We assume that module should be name in 'snake_case'.
        # Therefore, if import_item[0] starts with uppercase (likely to be
        # functions or constants), underscore (private / protected members) or
        # '*' (wildcard import), "import_is_module" will be False.
        import_is_module = import_item[0].islower()
      elif not module_spec.submodule_search_locations:
        # final_module is not a package
        import_is_module = False
      else:
        import_item_spec = FindModuleSpec(
            import_item, module_spec.submodule_search_locations)
        import_is_module = import_item_spec is not None

      if import_is_module:
        final_module = final_module + '.' + import_item

      import_list.append(final_module)

  return sorted(set(import_list))


def LoadRules(path):
  """Loads dependency rules from a given (YAML) configuration file.

  Args:
    path: A string of file path to a YAML config file.

  Returns:
    A dictionary of {package: imports} describing "'package' can only import
    from 'imports'".
  """
  with open(path, encoding='utf8') as fp:
    config = yaml.safe_load(fp)
  if (CONFIG_GROUPS not in config) or (CONFIG_RULES not in config):
    raise ValueError('Syntax error in %s' % path)

  groups = config[CONFIG_GROUPS]
  rules = {}
  for key, value in config[CONFIG_RULES].items():
    # Expand value into imports
    imports = []
    for package in value:
      match = re.match(CONFIG_GROUP_PATTERN, package)
      if match:
        imports += groups[match.group(1)]
      else:
        imports.append(package)

    match = re.match(CONFIG_GROUP_PATTERN, key)
    if match:
      # Duplicate multiple rules
      for module in groups[match.group(1)]:
        rules[module] = imports
    else:
      rules[key] = imports

  def RulePriority(key):
    """Priority of a rule.

    Larger number means more strict and should be used first.
    """
    if key.startswith('='):
      return 4
    if key.endswith('.*'):
      return 2
    if key == '*':
      return 1
    return 3

  return sorted(rules.items(),
                key=lambda k_v: (RulePriority(k_v[0]), k_v[0]),
                reverse=True)


def GetPackage(module):
  """Gets the package name containing a module.

  Returns the module itself if it's top level.
  """
  if '.' in module:
    return module.rpartition('.')[0]
  return module


def RuleMatch(rule, module):
  """Check if a rule match a module.

  If the rule starts with a "=", then the rule would be matched against the
  whole module, else it would be matched against the package name.

  If the rule ends with ".*", the rule would match the module and all
  submodules of it.

  The rule can also be "*" to match everything.

  For example, the following (rule, module) match:
    (*, x.y)
    (=x.y.z, x.y.z)
    (x.y, x.y.z)
    (x.y.* x.y.z)
    (x.y.*, x.y.z.w)

  The following (rule, module) doesn't match:
    (=x.y.z, x.y.z.w)
    (x.y, x.y)
    (x.y, x.y.z.w)
    (x.y.*, x.y)
  """
  if rule == '*':
    return True

  if rule.startswith('='):
    target = module
    rule = rule[1:]
  else:
    target = GetPackage(module)

  if rule.endswith('.*'):
    return target == rule[:-2] or target.startswith(rule[:-1])
  return target == rule


def FindRule(rules, module):
  """Find the first matching rule in rules for module."""
  for key, value in rules:
    if RuleMatch(key, module):
      return value
  raise ValueError('Module %s not found in rule.' % module)


def CheckDependencyList(rules, module, import_list):
  """Check if a module's import list is prohibited by the rule.

  Returns the list of prohibited imports.
  """
  rule = FindRule(rules, module)

  result = []
  for item in import_list:
    bad = True
    if any(RuleMatch(r, item) for r in rule):
      bad = False
    if bad:
      result.append(item)

  return result


def Check(filename, rules):
  """Check the file dependency by rule."""
  if os.path.splitext(filename)[1] != '.py':
    return None
  if filename.endswith('_unittest.py'):
    return None
  if filename.endswith('_mocked.py'):
    return None

  try:
    filename = os.path.abspath(filename)
    module_name = GuessModule(filename)
    if module_name is None:
      raise ValueError("%s is not in factory Python directory." % filename)

    import_list = GetImportList(filename, module_name)
    import_list = [x for x in import_list if not GuessIsBuiltinOrStdlib(x)]

    bad_imports = CheckDependencyList(rules, module_name, import_list)
    if bad_imports:
      raise ValueError('\n'.join('  x %s' % x for x in bad_imports))
    return None
  except Exception as e:
    error_msg = '--- %s (%s) ---\n%s' % (os.path.relpath(filename), module_name,
                                         e)
    return error_msg


def main():
  parser = argparse.ArgumentParser()
  parser.add_argument(
      'sources', metavar='SOURCE_CODE', nargs='*',
      help='The Python source code to check dependencies')
  parser.add_argument(
      '--parallel', '-p',
      action='store_true',
      help='Run the dependency checks in parallel')
  args = parser.parse_args()

  rules = LoadRules(os.path.join(os.path.dirname(__file__), 'deps.conf'))

  with multiprocessing.Pool(
      multiprocessing.cpu_count() if args.parallel else 1) as pool:

    return_value = 0
    for error_msg in pool.imap_unordered(
        functools.partial(Check, rules=rules), args.sources):
      if error_msg is not None:
        print(error_msg)
        return_value = 1
  sys.exit(return_value)


if __name__ == '__main__':
  main()
