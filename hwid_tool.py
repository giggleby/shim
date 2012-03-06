#!/usr/bin/env python
# Copyright (c) 2012 The Chromium OS Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

from argparse import ArgumentParser

import difflib
import logging
import os
import random
import re
import sys
import time
import zlib

from common import Error, Obj
from bom_names import BOM_NAME_SET
from hwid_database import InvalidDataError, MakeDatastoreSubclass
from hwid_database import YamlWrite, YamlRead


# The expected location of HWID data within a factory image.
DEFAULT_HWID_DATA_PATH= '/usr/local/factory/hwid'

COMPONENT_DB_FILENAME = 'component_db'


# Warning message prepended to all data files.
DATA_FILE_WARNING_MESSAGE_HEADER = '''
# WARNING: This file is AUTOMATICALLY GENERATED, do not edit.
# The proper way to modify this file is using the hwid_tool.
'''.strip()


# Possible life cycle stages for components and HWIDs.
LIFE_CYCLE_STAGES = [
    'supported',
    'qualified',
    'deprecated',
    'eol',
    'proposed']


MakeDatastoreSubclass('CompDb', {
    'component_list_deprecated': (list, str),
    'component_list_eol': (list, str),
    'component_list_qualified': (list, str),
    'component_list_supported': (list, str),
    'component_registry': (dict, (dict, str)),
    })

MakeDatastoreSubclass('Hwid', {
    'component_map': (dict, str),
    'variant_list': (list, str),
    })

MakeDatastoreSubclass('Device', {
    'bitmap_file_path': str,
    'hash_map': (dict, str),
    'hwid_list_deprecated': (list, str),
    'hwid_list_eol': (list, str),
    'hwid_list_qualified': (list, str),
    'hwid_list_supported': (list, str),
    'hwid_map': (dict, Hwid),
    'initial_config_map': (dict, (dict, str)),
    'initial_config_use_map': (dict, (list, str)),
    'release_map': (dict, (list, str)),
    'variant_map': (dict, (list, str)),
    'volatile_map': (dict, (dict, str)),
    'vpd_ro_field_list': (list, str),
    })


# TODO(tammo): Fix initial config to have canonical names for each
# 'probe result', stored as a map in device.

# TODO(tammo): Enforce that volatile canonical names (the keys in the
# hash_map) are all lower case, to allow for the special 'ANY' tag.

# TODO(tammo): For those routines that take 'data' as the first arg,
# consider making them methods of a DeviceDb class and then have the
# constructor for that class read the data from disk.

# TODO(tammo): Should release move into volatile?

# TODO(tammo): Refactor code to lift out the command line tool parts
# from the core functionality of the module.  Goal is that the key
# operations should be accessible with a meaningful programmatic API,
# and the command line tool parts should just be one of the clients of
# that API.


def HwidChecksum(text):
  return ('%04u' % (zlib.crc32(text) & 0xffffffffL))[-4:]


def FmtHwid(board, bom, volatile, variant):
  """Generate HWID string.  See the hwid spec for details."""
  text = '%s %s %s-%s' % (board, bom, variant, volatile)
  assert text.isupper(), 'HWID cannot have lower case text parts.'
  return str(text + ' ' + HwidChecksum(text))


def ParseHwid(hwid):
  """Parse HWID string details.  See the hwid spec for details."""
  parts = hwid.split()
  if len(parts) != 4:
    raise Error, ('illegal hwid %r, does not match ' % hwid +
                  '"BOARD BOM VARIANT-VOLATILE CHECKSUM" format')
  checksum = parts.pop()
  if checksum != HwidChecksum(' '.join(parts)):
    raise Error, 'bad checksum for hwid %r' % hwid
  varvol = parts.pop().split('-')
  if len(varvol) != 2:
    raise Error, 'bad variant-volatile part for hwid %r' % hwid
  variant, volatile = varvol
  board, bom = parts
  if not all(x.isalpha() for x in [board, bom, variant, volatile]):
    raise Error, 'bad (non-alpha) part for hwid %r' % hwid
  return Obj(board=board, bom=bom, variant=variant, volatile=volatile)


def ComponentConfigStr(component_map):
  """Represent component_map with a single canonical string.

  Component names are unique.  ANY and NONE are combined with the
  corresponding component class name to become unique.  The resulting
  substrings are sorted and concatenated.
  """
  def substr(comp_class, comp):
    return comp_class + '_' + comp if comp in ['ANY', 'NONE'] else comp
  return ' '.join(sorted(substr(k, v) for k, v in component_map.items()))


def IndentedStructuredPrint(depth, title, *content, **tagged_content):
  """Print YAML-like dict representation, but with fancy alignment and tagging.

  The content_dict data is formatted into key and value columns, such
  the key column is fixed width and all of the keys are right aligned.

  Args:
    depth: Number of empty spaces to prefix each output line with.
    title: Header line.  Ignored if ''/None, otherwise contents indented +2.
    content: Multiple dict or list/set objects.  If dict, each of its
      key-value pairs is printed colon-separated, one pair per line.
      The data on all lines are aligned around the colon characters.
      The keys are right aliged to the colon and the values left
      aligned.  If list or set, there is no alignment and the list
      elements are comma-separated.
    tagged_content: Dict of (tag: content) mappings. Content is
      formatted like content above, but each output line is prefixed
      with the tag in parens.
  Returns:
    Nothing.
  """
  if title:
    print ' ' * depth + title
    depth += 2
  lhs_width_list = [len(tag) + len(k) + len(tag)
                    for tag, elt in tagged_content.items()
                    for k in elt if isinstance(elt, dict)]
  lhs_width_list += [len(k) for elt in content
                     for k in elt if isinstance(elt, dict)]
  max_key_width = max(lhs_width_list) if lhs_width_list else 0
  def PrintElt(elt, tag):
    if isinstance(elt, dict):
      for k, v in sorted((k, v) for k, v in elt.items()):
        print '%s%s%s%s: %s' % (
          depth * ' ',
          tag,
          (max_key_width - len(tag) - len(k)) * ' ',
          k,
          'NONE' if v is None else ("''" if v == '' else v))
    if elt and (isinstance(elt, list) or isinstance(elt, set)):
      print (depth * ' ' + tag + ', '.join(str(s) for s in sorted(elt)))
  for elt in content:
    PrintElt(elt, '')
  for tag, elt in sorted(tagged_content.items()):
    PrintElt(elt, '(%s) ' % tag if tag != '' else '')
  print ''


# TODO(tammo): Move the below read and write into the hwid_database module.


def ReadDatastore(path):
  """Read the component_db and all device data files."""
  data = Obj(comp_db={}, device_db={})
  comp_db_path = os.path.join(path, COMPONENT_DB_FILENAME)
  if not os.path.isfile(comp_db_path):
    raise Error, 'ComponentDB not found (expected path is %r).' % comp_db_path
  with open(comp_db_path, 'r') as f:
    data.comp_db = CompDb.Decode(f.read())
  for entry in os.listdir(path):
    entry_path = os.path.join(path, entry)
    if not (entry.isalpha() and entry.isupper() and os.path.isfile(entry_path)):
      continue
    with open(entry_path, 'r') as f:
      try:
        data.device_db[entry] = Device.Decode(f.read())
      except InvalidDataError, e:
        logging.error('%r decode failed: %s' % (entry_path, e))
  return data


def WriteDatastore(path, data):
  """Write the component_db and all device data files."""
  def WriteOnDiff(filename, raw_internal_data):
    full_path = os.path.join(path, filename)
    internal_data = (DATA_FILE_WARNING_MESSAGE_HEADER.split('\n') +
                     raw_internal_data.strip('\n').split('\n'))
    if os.path.exists(full_path):
      with open(full_path, 'r') as f:
        file_data = map(lambda s: s.strip('\n'), f.readlines())
      diff = [line for line in difflib.unified_diff(file_data, internal_data)]
      if not diff:
        return
      logging.info('updating %s with changes:\n%s' %
                   (filename, '\n'.join(diff)))
    else:
      logging.info('creating new data file %s' % filename)
    with open(full_path, 'w') as f:
      f.write('%s\n' % '\n'.join(internal_data))
  WriteOnDiff(COMPONENT_DB_FILENAME, data.comp_db.Encode())
  for device_name, device in data.device_db.items():
    WriteOnDiff(device_name, device.Encode())


def GetAvailableBomNames(data, board, count):
  """Return count random bom names that are not yet used by board."""
  existing_bom_names = set(bn for bn in data.device_db[board].hwid_map)
  available_names = [bn for bn in BOM_NAME_SET if bn not in existing_bom_names]
  random.shuffle(available_names)
  if len(available_names) < count:
    raise Error('too few available bom names (only %d left)' % len(available))
  return available_names[:count]


# TODO(tammo): Generate re-usable derived data like status maps when
# data is initially loaded.  This also acts as sanity checking.
def CalcHwidStatusMap(device):
  """TODO(tammo): XXX more here XXX."""
  status_map = {}
  for status in LIFE_CYCLE_STAGES:
    for prefix in getattr(device, 'hwid_list_' + status, []):
      parts = reversed(prefix.split('-'))
      bom_status_map = status_map.setdefault(next(parts), {})
      volatile = next(parts, None)
      variant = next(parts, None)
  # TODO(tammo): Finish this, then get rid of LookupHwidStatus.


def LookupHwidStatus(device, bom, volatile, variant):
  """Match hwid details against prefix-based status data.

  Returns:
    A status string, or None if no status was found.
  """
  target_pattern = (bom + '-' + volatile + '-' + variant)
  def ContainsHwid(prefix_list):
    for prefix in prefix_list:
      if target_pattern.startswith(prefix):
        return True
  for status in LIFE_CYCLE_STAGES:
    if ContainsHwid(getattr(device, 'hwid_list_' + status, [])):
      return status
  return None


def CalcCompDbClassMap(comp_db):
  """Return dict of (comp_name: comp_class) mappings."""
  return dict((comp_name, comp_class) for comp_name in comp_map
              for comp_class, comp_map in comp_db.component_registry.items())


def CalcCompDbProbeValMap(comp_db):
  """Return dict of (probe_value: comp_name) mappings."""
  return dict((probe_value, comp_name)
              for comp_map in comp_db.component_registry.values()
              for comp_name, probe_value in comp_map.items())


def CalcReverseComponentMap(hwid_map):
  """Return dict of (comp_class: dict of (component: bom name set)) mappings.

  For each component in each comp_class, reveals the set of boms
  containing that component.
  """
  comp_class_map = {}
  for bom, hwid in hwid_map.items():
    for comp_class, comp in hwid.component_map.items():
      comp_map = comp_class_map.setdefault(comp_class, {})
      comp_bom_set = comp_map.setdefault(comp, set())
      comp_bom_set.add(bom)
  return comp_class_map


def CalcBiggestBomSet(rev_comp_map):
  """For the component with the most boms using it, return that bom set.

  If there multiple components have equal numbers of boms, only one
  will be returned.  Fails when no componets have any boms (KeyError).
  """
  return sorted([(len(bom_set), bom_set)
                 for comp_map in rev_comp_map.values()
                 for bom_set in comp_map.values()]).pop()[1]


def CalcFullBomSet(rev_comp_map):
  """Return the superset of all bom sets from the rev_comp_map."""
  return set(bom for comp_map in rev_comp_map.values()
             for bom_set in comp_map.values() for bom in bom_set)


def CalcCommonComponentMap(rev_comp_map):
  """Return (comp_class: comp) dict for only components with maximal bom set."""
  full_bom_set = CalcFullBomSet(rev_comp_map)
  return dict(
      (comp_class, comp)
      for comp_class, comp_map in rev_comp_map.items()
      for comp, comp_bom_set in comp_map.items()
      if comp_bom_set == full_bom_set)


def SplitReverseComponentMap(rev_comp_map):
  """Parition rev_comp_map into left and right parts by largest bom set.

  Calculate the set of common components shared by all of the bom in
  the rev_comp_map.  For the remaining components, use the largest set
  of boms that share one component as a radix and partition the
  remaining rev_comp_map data into left (data for boms in the largest
  bom set) and right (all other data).

  Returns:
    Obj containing the left and right rev_comp_map partitions, a dict
    of common components, and the bom superset for the input
    rev_comp_map (meaning the bom set matching the common components).
  """
  if not rev_comp_map:
    return None
  full_bom_set = CalcFullBomSet(rev_comp_map)
  split_bom_set = CalcBiggestBomSet(rev_comp_map)
  common_comp_map = {}
  left_rev_comp_map = {}
  right_rev_comp_map = {}
  for comp_class, comp_map in rev_comp_map.items():
    for comp, bom_set in comp_map.items():
      if bom_set == full_bom_set:
        common_comp_map[comp_class] = comp
      else:
        overlap_bom_set = bom_set & split_bom_set
        if overlap_bom_set:
          left_rev_comp_map.setdefault(comp_class, {})[comp] = overlap_bom_set
        extra_bom_set = bom_set - split_bom_set
        if extra_bom_set:
          right_rev_comp_map.setdefault(comp_class, {})[comp] = extra_bom_set
  return Obj(target_bom_set=full_bom_set,
             common_comp_map=common_comp_map,
             left_rev_comp_map=left_rev_comp_map,
             right_rev_comp_map=right_rev_comp_map)


def TraverseCompMapHierarchy(rev_comp_map, branch_cb, leaf_cb, cb_arg):
  """Derive component-usage hwid hierarchy and eval callback at key points.

  The component data in rev_comp_map is used to derive a tree
  structure where branch nodes indicate a set of components that are
  shared by all of the boms across the branches subtrees.  Callback
  functions are evaluated both for each branch and also for each leaf
  node.

  Args:
    rev_comp_map: A reverse component map.
    branch_cb: Callback funtion to be executed at branch nodes
      (indicating the existence of common components).
    leaf_cb: Callback function to be executed at lead nodes (meaning
      specific boms).
    cb_arg: Argument passed to both callbacks.  Branch callbacks must
      return updated versions of this data, which will be passsed to
      the recursive traversal of contained subtrees.
  Returns:
    Nothing.
  """
  def SubTraverse(rev_comp_map, cb_arg, depth):
    """Recursive helper; tracks recursion depth and allows cb_arg update."""
    split = SplitReverseComponentMap(rev_comp_map)
    if split is None:
      return
    if split.common_comp_map:
      cb_arg = branch_cb(depth, cb_arg, split.target_bom_set,
                         split.common_comp_map)
      depth += 1
    SubTraverse(split.left_rev_comp_map, cb_arg, depth)
    if not split.left_rev_comp_map:
      leaf_cb(depth, cb_arg, split.target_bom_set)
    SubTraverse(split.right_rev_comp_map, cb_arg, depth)
  SubTraverse(rev_comp_map, cb_arg, 0)


def FilterExternalHwidAttrs(device, target_bom_set,
                            masks=Obj(initial_config_set=set(),
                                      release_set=set())):
  """Return those attributes shared by the target boms but not masked out.

  Calculate the sets of release and initial_config values that are
  shared by all of the boms in the target_bom_set.  Then filter these
  sets to contain only values not already present in their respective
  mask.
  """
  # TODO(tammo): Instead pre-compute reverse maps, and return unions.
  return Obj(
      release_set=set(
          release for release, bom_list in device.release_map.items()
          if (release not in masks.release_set and
              target_bom_set <= set(bom_list))),
      initial_config_set=set(
          ic for ic, bom_list in device.initial_config_use_map.items()
          if (ic not in masks.initial_config_set and
              target_bom_set <= set(bom_list))))


def PrintHwidHierarchy(board, device, hwid_map):
  """Hierarchically show all details for all HWIDs for the specified board.

  Details include the component configuration, initial config, and release.
  """
  def UpdateMasks(a, b):
    return Obj(release_set=(a.release_set | b.release_set),
               initial_config_set=(a.initial_config_set | b.initial_config_set))
  def ShowCommon(depth, masks, bom_set, common_comp_map):
    misc_common = FilterExternalHwidAttrs(device, bom_set, masks)
    IndentedStructuredPrint(depth * 2, '-'.join(sorted(bom_set)),
                            comp=common_comp_map,
                            initial_config=misc_common.initial_config_set,
                            release=misc_common.release_set)
    return UpdateMasks(masks, misc_common)
  def ShowHwids(depth, masks, bom_set):
    for bom in bom_set:
      hwid = hwid_map[bom]
      misc_common = FilterExternalHwidAttrs(device, set([bom]), masks)
      variants = dict((FmtHwid(board, bom, volind, variant),
                       ','.join(device.variant_map[variant]))
                      for variant in hwid.variant_list
                      for volind in device.volatile_map
                      if LookupHwidStatus(device, bom, volind, variant))
      if misc_common.initial_config_set or misc_common.release_set:
        IndentedStructuredPrint((depth + 1) * 2, bom,
                                initial_config=misc_common.initial_config_set,
                                release=misc_common.release_set)
        IndentedStructuredPrint((depth + 2) * 2, None, variants)
      else:
        IndentedStructuredPrint(depth * 2, None, variants)
  # TODO(tammo): Fix the cb arg usage to allow omission here.
  TraverseCompMapHierarchy(CalcReverseComponentMap(hwid_map),
                           ShowCommon, ShowHwids,
                           Obj(initial_config_set=set(),
                               release_set=set()))


def ProcessComponentCrossproduct(data, board, comp_list):
  """Return new combinations for board using the components from comp_list.

  The components in the comp_list are supplemented with those for any
  missing component classes if a common component can be found for
  that component class for the specified board.  The result is the
  collection of component configurations that are not already
  registered for the board, generated using the components in
  comp_list.  For example, if comp_list contains 2 components of one
  comp_class and 3 components of another, and if all of these are new
  to the board, this routine will produce 2 * 3 = 6 new component
  configurations.
  """
  def ClassifyInputComponents(comp_list):
    """Return dict of (comp_class: comp list), associating comps to classes."""
    comp_db_class_map = CalcCompDbClassMap(data.comp_db)
    comp_class_subset = set(comp_db_class_map[comp] for comp in comp_list)
    return dict((comp_class, [comp for comp in comp_list
                              if comp_db_class_map[comp] == comp_class])
                for comp_class in comp_class_subset)
  def DoCrossproduct(available_comp_data_list, target_comp_map_list):
    """Return list of comp maps corresonding to all possible combinations.

    Remove (comp_class, comp_list) pairs from the available list and
    combine each of these components recursively with those left of
    the available list.  Result is a list of (comp_class: comp) dicts.
    """
    if not available_comp_data_list:
      return [dict(target_comp_map_list)]
    (comp_class, comp_list) = available_comp_data_list[0]
    result = []
    for comp in comp_list:
      new_target_comp_map_list = target_comp_map_list + [(comp_class, comp)]
      result += DoCrossproduct(available_comp_data_list[1:],
                               new_target_comp_map_list)
    return result
  comp_map = ClassifyInputComponents(comp_list)
  hwid_map = data.device_db[board].hwid_map
  rev_comp_map = CalcReverseComponentMap(hwid_map)
  common_comp_map = CalcCommonComponentMap(rev_comp_map)
  class_coverage = set(comp_map) | set(common_comp_map)
  if class_coverage != set(rev_comp_map):
    raise Error('need component data for: %s' % ', '.join(
        set(rev_comp_map) - class_coverage))
  existing_comp_map_str_set = set(ComponentConfigStr(hwid.component_map)
                                  for hwid in hwid_map.values())
  new_comp_map_list = DoCrossproduct(comp_map.items(), common_comp_map.items())
  return [comp_map for comp_map in new_comp_map_list
          if ComponentConfigStr(comp_map) not in existing_comp_map_str_set]


def CookComponentProbeResults(comp_db, probe_results):
  """TODO(tammo): Add more here XXX."""
  match = Obj(known={}, unknown={})
  comp_reference_map = CalcCompDbProbeValMap(comp_db)
  for probe_class, probe_value in probe_results.components.items():
    if probe_value is None:
      continue
    if probe_value in comp_reference_map:
      match.known[probe_class] = comp_reference_map[probe_value]
    else:
      match.unknown[probe_class] = probe_value
  return match


def CookDeviceProbeResults(device, probe_results):
  """TODO(tammo): Add more here XXX."""
  match = Obj(volatile_set=set(), initial_config_set=set())
  # TODO(tammo): Precompute this reverse map.
  hash_reference_map = dict((v, c) for c, v in device.hash_map.items())
  vol_map = dict((c, hash_reference_map[v])
                 for c, v in probe_results.volatiles.items()
                 if v in hash_reference_map)
  for volatile, vol_reference_map in device.volatile_map.items():
    if all(vol_reference_map[c] == v for c, v in vol_map.items()
           if vol_reference_map[c] != 'ANY'):
      match.volatile_set.add(volatile)
  for initial_config, ic_map in device.initial_config_map.items():
    if all(probe_results.initial_configs.get(ic_class, None) != ic_value
           for ic_class, ic_value in ic_map.items()):
      match.initial_config_set.add(initial_config)
  return match


def LookupHwidProperties(data, hwid):
  """TODO(tammo): Add more here XXX."""
  props = ParseHwid(hwid)
  if props.board not in data.device_db:
    raise Error, 'hwid %r board %s could not be found' % (hwid, props.board)
  device = data.device_db[props.board]
  if props.bom not in device.hwid_map:
    raise Error, 'hwid %r bom %s could not be found' % (hwid, props.bom)
  hwid_details = device.hwid_map[props.bom]
  if props.variant not in hwid_details.variant_list:
    raise Error, ('hwid %r variant %s does not match database' %
                  (hwid, props.variant))
  if props.volatile not in device.volatile_map:
    raise Error, ('hwid %r volatile %s does not match database' %
                  (hwid, props.volatile))
  props.status = LookupHwidStatus(device, props.bom,
                                  props.volatile, props.variant)
  # TODO(tammo): Refactor if FilterExternalHwidAttrs is pre-computed.
  misc_attrs = FilterExternalHwidAttrs(device, set([props.bom]))
  if len(misc_attrs.release_set) != 1:
    raise Error, 'hwid %r matches zero or multiple release values'
  props.release = next(iter(misc_attrs.release_set))
  props.initial_config = next(iter(misc_attrs.initial_config_set), None)
  props.vpd_ro_field_list = device.vpd_ro_field_list
  props.bitmap_file_path = device.bitmap_file_path
  props.component_map = hwid_details.component_map
  return props


# List of sub-commands that can be specified as command line
# arguments.  This list is populated by the @Command decorators around
# the corresponding command implementation functions.
G_commands = {}


def Command(cmd_name, *arg_list):
  """Decorator to populate the global command list.

  Function doc strings are extracted and shown to users as part of the
  help message for each command.
  """
  def Decorate(fun):
    doc = fun.__doc__ if fun.__doc__ else None
    G_commands[cmd_name] = (fun, doc, arg_list)
    return fun
  return Decorate


def CmdArg(*tags, **kvargs):
  """Allow decorator arg specification using real argparse syntax."""
  return (tags, kvargs)


@Command('create_hwids',
         CmdArg('-b', '--board', required=True),
         CmdArg('-c', '--comps', nargs='*', required=True),
         CmdArg('-x', '--make_it_so', action='store_true'),
         CmdArg('-v', '--variants', nargs='*'))
def CreateHwidsCommand(config, data):
  """Derive new HWIDs from the cross-product of specified components.

  For the specific board, the specified components indicate a
  potential set of new HWIDs.  It is only necessary to specify
  components that are different from those commonly shared by the
  boards existing HWIDs.  The target set of new HWIDs is then derived
  by looking at the maxmimal number of combinations between the new
  differing components.

  By default this command just prints the set of HWIDs that would be
  added.  To actually create them, it is necessary to specify the
  make_it_so option.
  """
  # TODO(tammo): Validate inputs -- comp names, variant names, etc.
  comp_map_list = ProcessComponentCrossproduct(data, config.board, config.comps)
  bom_name_list = GetAvailableBomNames(data, config.board, len(comp_map_list))
  variant_list = config.variants if config.variants else []
  hwid_map = dict((bom_name, Hwid(component_map=comp_map,
                                  variant_list=variant_list))
                  for bom_name, comp_map in zip(bom_name_list, comp_map_list))
  device = data.device_db[config.board]
  device.hwid_list_proposed = bom_name_list
  PrintHwidHierarchy(config.board, device, hwid_map)
  if config.make_it_so:
    #TODO(tammo): Actually add to the device hwid_map, and qualify.
    pass


@Command('hwid_overview',
         CmdArg('-b', '--board'))
def HwidHierarchyViewCommand(config, data):
  """Show HWIDs in visually efficient hierarchical manner.

  Starting with the set of all HWIDs for each board or a selected
  board, show the set of common components and data values, then find
  subsets of HWIDs with maximally shared data and repeat until there
  are only singleton sets, at which point print the full HWID strings.
  """
  for board, device in data.device_db.items():
    if config.board:
      if not config.board == board:
        continue
    else:
      print '---- %s ----\n' % board
    PrintHwidHierarchy(board, device, device.hwid_map)


@Command('list_hwids',
         CmdArg('-b', '--board'),
         CmdArg('-s', '--status', default='supported'),
         CmdArg('-v', '--verbose', action='store_true'))
def ListHwidsCommand(config, data):
  """Print sorted list of supported HWIDs.

  Optionally list HWIDs for other status values, or '' for all HWIDs.
  Optionally show the status of each HWID.  Optionally limit the list
  to a specific board.
  """
  result_list = []
  for board, device in data.device_db.items():
    if config.board:
      if not config.board == board:
        continue
    for bom, hwid in device.hwid_map.items():
      for volind in device.volatile_map:
        for variant in hwid.variant_list:
          status = LookupHwidStatus(device, bom, volind, variant)
          if (config.status != '' and
              (status is None or config.status != status)):
            continue
          result = FmtHwid(board, bom, volind, variant)
          if config.verbose:
            result = '%s: %s' % (status, result)
          result_list.append(result)
  for result in sorted(result_list):
    print result


@Command('component_breakdown',
         CmdArg('-b', '--board'))
def ComponentBreakdownCommand(config, data):
  """Map components to HWIDs, organized by component.

  For all boards, or for a specified board, first show the set of
  common components.  For all the non-common components, show a list
  of BOM names that use them.
  """
  for board, device in data.device_db.items():
    if config.board:
      if not config.board == board:
        continue
    else:
      print '---- %s ----' % board
    rev_comp_map = CalcReverseComponentMap(device.hwid_map)
    common_comp_map = CalcCommonComponentMap(rev_comp_map)
    IndentedStructuredPrint(0, 'common:', common_comp_map)
    remaining_comp_class_set = set(rev_comp_map) - set(common_comp_map)
    sorted_remaining_comp_class_list = sorted(
        [(len(rev_comp_map[comp_class]), comp_class)
         for comp_class in  remaining_comp_class_set])
    while sorted_remaining_comp_class_list:
      comp_class = sorted_remaining_comp_class_list.pop()[1]
      comp_map = dict((comp, ', '.join(sorted(bom_set)))
                      for comp, bom_set in rev_comp_map[comp_class].items())
      IndentedStructuredPrint(0, comp_class + ':', comp_map)


@Command('probe_device',
         CmdArg('-b', '--board'),
         CmdArg('-c', '--classes', nargs='*'),
         CmdArg('-r', '--raw', action='store_true'))
def ProbeDeviceProperties(config, data):
  # TODO(tammo): Implement classes arg behavior.
  # TODO(tammo): Move this command into gooftool to avoid having to
  # load the probe module here. The probe module depends on other
  # modules that are not available except on DUT machines.
  from probe import Probe
  probe_results = Probe(data.comp_db.component_registry)
  if config.raw:
    print YamlWrite(probe_results.__dict__)
    return
  IndentedStructuredPrint(0, 'component probe results:',
                          probe_results.components)
  missing_classes = (set(data.comp_db.component_registry) -
  set(probe_results.components))
  if missing_classes:
    logging.warning('missing results for comp classes: %s' %
                    ', '.join(missing_classes))
  cooked_components = CookComponentProbeResults(data.comp_db, probe_results)
  if cooked_components.known:
    IndentedStructuredPrint(0, 'known components:', cooked_components.known)
  if cooked_components.unknown:
    IndentedStructuredPrint(0, 'unknown components:', cooked_components.unknown)
  if config.board:
    if config.board not in data.device_db:
      logging.critical('unknown board %r (known boards: %s' %
                       (config.board, ', '.join(sorted(data.device_db))))
      return
    device = data.device_db[config.board]
    cooked_device_details = CookDeviceProbeResults(device, probe_results)
    IndentedStructuredPrint(0, 'volatile probe results:',
                            probe_results.volatiles)
    IndentedStructuredPrint(0, 'matching volatile tags:',
                            cooked_device_details.volatile_set)
    IndentedStructuredPrint(0, 'initial_config probe results:',
                            probe_results.initial_configs)
    IndentedStructuredPrint(0, 'matching initial_config tags:',
                            cooked_device_details.initial_config_set)


@Command('assimilate_probe_data',
         CmdArg('-b', '--board'))
def AssimilateProbeData(config, data):
  """Read new data from stdin then merge into existing data.

  TODO(tammo): Add more here.
  """
  probe_results = Obj(**YamlRead(sys.stdin.read()))
  components = getattr(probe_results, 'components', {})
  registry = data.comp_db.component_registry
  if not set(components) <= set(registry):
    logging.critical('data contains component classes that are not preset in '
                     'the component_db, specifically %r' %
                     sorted(set(components) - set(registry)))
  reverse_registry = CalcCompDbProbeValMap(data.comp_db)
  for comp_class, probe_value in components.items():
    if probe_value is None or probe_value in reverse_registry:
      continue
    comp_map = registry[comp_class]
    comp_map['%s_%d' % (comp_class, len(comp_map))] = probe_value
  if not config.board:
    if (hasattr(probe_results, 'volatile') or
        hasattr(probe_results, 'initial_config')):
      logging.warning('volatile and/or initial_config data is only '
                      'assimilated when a board is specified')
    return
  device = data.device_db[config.board]


@Command('board_create',
         CmdArg('board_name'))
def CreateBoard(config, data):
  """Create an fresh empty board with specified name."""
  if not config.board_name.isalpha():
    print 'ERROR: Board names must be alpha-only.'
    return
  board_name = config.board_name.upper()
  if board_name in data.device_db:
    print 'ERROR: Board %s already exists.' % board_name
    return
  data.device_db[board_name] = Device.New()
  print data.device_db[board_name].__dict__


@Command('filter_database',
         CmdArg('-b', '--board', required=True),
         CmdArg('-d', '--dest_dir', required=True),
         CmdArg('-s', '--by_status', nargs='*', default=['supported']))
def FilterDatabase(config, data):
  """Generate trimmed down board data file and corresponding component_db.

  Generate a board data file containing only those boms matching the
  specified status, and only that portion of the related board data
  that is used by those boms.  Also produce a component_db which
  contains entries only for those components used by the selected
  boms.
  """
  # TODO(tammo): Validate inputs -- board name, status, etc.
  device = data.device_db[config.board]
  target_hwid_map = {}
  target_volatile_set = set()
  target_variant_set = set()
  for bom, hwid in device.hwid_map.items():
    for variant in hwid.variant_list:
      for volatile in device.volatile_map:
        status = LookupHwidStatus(device, bom, volatile, variant)
        if status in config.by_status:
          variant_map = target_hwid_map.setdefault(bom, {})
          volatile_list = variant_map.setdefault(variant, [])
          volatile_list.append(volatile)
          target_volatile_set.add(volatile)
          target_variant_set.add(variant)
  filtered_comp_db = CompDb.New()
  filtered_device = Device.New()
  for bom in target_hwid_map:
    hwid = device.hwid_map[bom]
    filtered_hwid = Hwid.New()
    filtered_hwid.component_map = hwid.component_map
    filtered_hwid.variant_list = list(set(hwid.variant_list) &
                                      target_variant_set)
    filtered_device.hwid_map[bom] = filtered_hwid
    for comp_class, comp_name in hwid.component_map.items():
      filtered_comp_db.component_registry[comp_class] = \
          data.comp_db.component_registry[comp_class]
  for volatile_index in target_volatile_set:
    volatile_details = device.volatile_map[volatile_index]
    filtered_device.volatile_map[volatile_index] = volatile_details
    for volatile_class, volatile_name in volatile_details.items():
      volatile_value = device.hash_map[volatile_name]
      filtered_device.hash_map[volatile_name] = volatile_value
  for variant_index in target_variant_set:
    variant_details = device.variant_map[variant_index]
    filtered_device.variant_map[variant_index] = variant_details
  filtered_device.bitmap_file_path = device.bitmap_file_path
  filtered_device.vpd_ro_field_list = device.vpd_ro_field_list
  WriteDatastore(config.dest_dir,
                 Obj(comp_db=filtered_comp_db,
                     device_db={config.board: filtered_device}))
  # TODO(tammo): Also filter initial_config once the schema for that
  # has been refactored to be cleaner.
  # TODO(tammo): Also filter status for both boms and components once
  # the schema for that has been refactored to be cleaner.


class HackedArgumentParser(ArgumentParser):
  """Replace the usage and help strings to better format command names.

  The default formatting is terrible, cramming all the command names
  into one line with no spacing so that they are very hard to
  copy-paste.  Instead format command names one-per-line.  For
  simplicity make usage just return the help message text.

  Reformatting is done using regexp-substitution because the argparse
  formatting internals are explicitly declared to be private, and so
  doing things this way should be no less fragile than trying to
  replace the relevant argparse internals.
  """

  def format_sub_cmd_menu(self):
    """Return str with aligned list of 'cmd-name : first-doc-line' strs."""
    max_cmd_len = max(len(c) for c in G_commands)
    def format_item(cmd_name):
      doc = G_commands[cmd_name][1]
      doc = '' if doc is None else ' : ' + doc.split('\n')[0]
      return (max_cmd_len - len(cmd_name) + 2) * ' ' + cmd_name + doc
    return '\n'.join(format_item(cmd_name) for cmd_name in sorted(G_commands))

  def format_help(self):
    s = ArgumentParser.format_help(self)
    s = re.sub(r'(?ms)\].*{.*}.*\.\.\.', r'] <sub-command>', s)
    s = re.sub(r'(?ms)(positional.*)(optional arguments:)',
               r'sub-commands:\n%s\n\n\2' % self.format_sub_cmd_menu(), s)
    return s

  def format_usage(self):
    return self.format_help() + '\n'


def ParseCmdline():
  """Return object containing all argparse-processed command line data."""
  parser = HackedArgumentParser(
      description='Visualize and/or modify HWID and related component data.')
  parser.add_argument('-p', '--data_path', metavar='PATH',
                      default=DEFAULT_HWID_DATA_PATH)
  parser.add_argument('-v', '--verbosity', choices='01234', default='2')
  parser.add_argument('-l', '--log_file')
  subparsers = parser.add_subparsers(dest='command_name')
  for cmd_name, (fun, doc, arg_list) in G_commands.items():
    subparser = subparsers.add_parser(cmd_name, description=doc)
    subparser.set_defaults(command=fun)
    for (tags, kvargs) in arg_list:
      subparser.add_argument(*tags, **kvargs)
  return parser.parse_args()


def SetupLogging(config):
  """Configure logging level, format, and target file/stream."""
  logging.basicConfig(
      format='%(levelname)-8s %(asctime)-8s %(message)s',
      datefmt='%H:%M:%S',
      level={4: logging.DEBUG, 3: logging.INFO, 2: logging.WARNING,
             1: logging.ERROR, 0: logging.CRITICAL}[int(config.verbosity)],
      **({'filename': config.log_file} if config.log_file else {}))
  logging.Formatter.converter = time.gmtime
  logging.info(time.strftime('%Y.%m.%d %Z', time.gmtime()))


def Main():
  """Run sub-command specified by the command line args."""
  config = ParseCmdline()
  SetupLogging(config)
  data = ReadDatastore(config.data_path)
  try:
    config.command(config, data)
  except Error, e:
    logging.exception(e)
    sys.exit('ERROR: %s' % e)
  except Exception, e:
    logging.exception(e)
    sys.exit('UNCAUGHT RUNTIME EXCEPTION %s' % e)
  WriteDatastore(config.data_path, data)


if __name__ == '__main__':
  Main()
