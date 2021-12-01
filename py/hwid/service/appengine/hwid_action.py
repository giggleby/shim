# Copyright 2021 The Chromium OS Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.
"""Defines available actions upon a specific HWID DB."""

import collections
import copy
from typing import Dict, List, NamedTuple, Optional, Set

from cros.factory.hwid.service.appengine \
    import verification_payload_generator as vpg_module
from cros.factory.hwid.v3 import contents_analyzer as v3_contents_analyzer
from cros.factory.hwid.v3 import database as v3_database


class HWIDDecodeError(KeyError):
  """Indicates a valid-format HWID does not map to a valid value."""


class InvalidHWIDError(ValueError):
  """Indicates a HWID is malformed."""


class NotSupportedError(ValueError):
  """Indicates that the method is not supported by the specific HWID version."""


class HWIDActionError(RuntimeError):
  """Indicates a server error."""


class Component(
    collections.namedtuple(
        'Component',
        ['cls', 'name', 'information', 'is_vp_related', 'fields'])):
  """A single BOM component.

  Attributes:
    cls string The component-class.
    name string The canonical name.
    information dict (optional) The extra information bound with the component.
    is_vp_related bool Whether this component is a source of the verification
        payload.
    fields dict (optional) The detail fields of the component.
  """

  def __new__(cls, cls_, name, information=None, is_vp_related=False,
              fields=None):
    if fields is None:
      fields = {}
    return super(Component, cls).__new__(cls, cls_, name, information,
                                         is_vp_related, fields)


class Label(NamedTuple):
  """A BOM label.

  Attributes:
    cls string The component-class.
    name string The label name.
    value string The value for this label, if any.
  """
  cls: str
  name: str
  value: Optional[str]


class BOM:
  """An abstraction of a BOM with both components and labels."""

  def __init__(self):
    self._components = {}
    self._labels = {}
    self.phase = ''
    self.project = None

  def HasComponent(self, component):
    """Tests whether the bom has a component."""
    return (component.cls in self._components and
            any(component.name == comp.name
                for comp in self._components[component.cls]))

  def GetComponents(self, cls=None):
    """Gets the components of this bom, optionally filtered by class."""
    if cls:
      if cls not in self._components:
        return []
      if not self._components[cls]:
        return [Component(cls, None, None)]
      return copy.deepcopy(self._components[cls])

    components = []
    for comp_class, comps in self._components.items():
      if comps == list():
        components.append(Component(comp_class, None, None))
      else:
        components.extend(copy.deepcopy(comps))

    return components

  def AddComponent(self, cls, name=None, information=None, is_vp_related=False,
                   fields=None):
    """Adds a component to this bom.

    The method must be supplied at least a component class.  If no name is
    specified then the component class will be present but empty.

    Args:
      cls: The component class.
      name: The name of the bom.
      information: (optional) The extra information bound with the
                   component.
      fields dict (optional) The detail fields of the component.
    """
    if cls not in self._components:
      self._components[cls] = []

    if name:
      self._components[cls].append(
          Component(cls, name, information, is_vp_related, fields))

  def AddAllComponents(self, component_dict, comp_db=None, verbose=False,
                       waived_comp_categories=None, require_vp_info=False):
    """Adds a dict of components to this bom.

    This dict should be of the form class -> name and can take either a single
    name or list of names in each entry.  This makes it easy to add all
    components as extract from a YAML file or similar.

    Args:
      component_dict: A dictionary of components to add.
      comp_db: The database for additional component information retrieval.
      verbose: Adds all fields of the component detail if set to True.
      waived_comp_categories: List of waived component categories which means
      they are not verification-payload-related.
      require_vp_info: A bool to indicate if the is_vp_related field of
          each component is required.
    Returns:
      self
    Raises:
      ValueError: if any of the classes are None.
    """
    if waived_comp_categories is None:
      waived_comp_categories = []
    if comp_db and require_vp_info:
      vp_related_comps = set(
          vpg_module.GetAllComponentVerificationPayloadPieces(
              comp_db, waived_comp_categories))
    else:
      vp_related_comps = set()

    for component_class, component_val in component_dict.items():
      db_components = comp_db and comp_db.GetComponents(component_class)
      if isinstance(component_val, str):
        comp_info = db_components and db_components.get(component_val)
        fields = comp_info.values if verbose and comp_info else None
        self.AddComponent(component_class, component_dict[component_class],
                          comp_info and comp_info.information,
                          (component_class, component_val) in vp_related_comps,
                          fields)
      else:
        for component_name in component_val:
          if isinstance(component_name, str):
            comp_info = db_components and db_components.get(component_name)
            fields = comp_info.values if verbose and comp_info else None
            self.AddComponent(component_class, component_name, comp_info and
                              comp_info.information,
                              (component_class, component_name)
                              in vp_related_comps, fields)

  def HasLabel(self, label):
    """Test whether the BOM has a label."""
    return label.cls in self._labels and label.name in self._labels[label.cls]

  def GetLabels(self, cls=None):
    """Gets the labels of this bom, optionally filtered by class."""
    if cls:
      if cls in self._labels:
        return [
            Label(cls, name, value)
            for name, values in self._labels[cls].items()
            for value in values
        ]
      return []
    return [
        Label(cls, name, value) for cls in self._labels
        for name, values in self._labels[cls].items() for value in values
    ]

  def AddLabel(self, cls, name, value=None):
    """Adds a label to this bom.

    The method must be supplied at least a label name.  If no class is
    specified then the label is assumed to be on the BOM as a whole.

    Args:
      cls: The component class.
      name: The name of the label.
      value: (optional) The label value or True for a valueless label.
    Returns:
      self
    Raises:
      ValueError: when no name is specified.
    """
    if not cls or not name:
      raise ValueError('Labels must have a class and name.')

    if cls not in self._labels:
      self._labels[cls] = {}

    if name in self._labels[cls]:
      self._labels[cls][name].append(value)
    else:
      self._labels[cls][name] = [value]

  def AddAllLabels(self, label_dict):
    """Adds a dict of labels to this bom.

    Args:
      label_dict: A dictionary with {class: {name: value}} mappings.
    Returns:
      self
    Raises:
      ValueError: if any of the values are None.
    """

    for cls in label_dict:
      for name in label_dict[cls]:
        value = label_dict[cls][name]
        self.AddLabel(cls, name, value)


DBValidationErrorCode = v3_contents_analyzer.ErrorCode
DBValidationError = v3_contents_analyzer.Error
DBNameChangedComponentInfo = v3_contents_analyzer.NameChangedComponentInfo


class DBEditableSectionChangeInfo(NamedTuple):
  # An fingerprint value represents this change.  Same value implies that both
  # the change source and destination are the same.
  fingerprint: str

  # The full HWID DB contents after change.
  new_hwid_db_contents: str

  # Reasons that this change is considered invalid.
  invalid_reasons: Optional[List[DBValidationError]]

  # Newly added HWID components, categorized by the component class.
  new_hwid_comps: Optional[Dict[str, List[DBNameChangedComponentInfo]]]

  @property
  def is_change_valid(self):
    return not self.invalid_reasons


DBEditableSectionAnalysisReport = v3_contents_analyzer.ChangeAnalysisReport
DBEditableSectionLineAnalysisResult = v3_contents_analyzer.DBLineAnalysisResult
DBHWIDComponentAnalysisResult = v3_contents_analyzer.HWIDComponentAnalysisResult


class BundleResourceInfo(NamedTuple):
  fingerprint: str


class BundleInfo(NamedTuple):
  bundle_contents: bytes
  bundle_file_ext: str


class HWIDAction:
  HWID_VERSION: int

  def GetBOMAndConfigless(self, hwid_string: str,
                          verbose: Optional[bool] = False,
                          waived_comp_categories: Optional[List[str]] = None,
                          require_vp_info: Optional[bool] = False):
    """Get the BOM and configless field for a given HWID.

    Args:
      hwid_string: The HWID.
      verbose: Returns all fields in component detail if set to True.
      waived_comp_categories: List of waived component categories which means
          they are not verification-payload-related.
      require_vp_info: A bool to indicate if the is_vp_related field of
          each component is required.

    Returns:
      A bom dict and configless field dict.
      If there is no configless field in given HWID, return BOM dict and None.

    Raises:
      HWIDDecodeError: If a portion of the HWID is not found.
      InvalidHWIDError: If the HWID is invalid.
      NotSupportedError: If this function is not supported by the HWID version.
    """
    raise NotSupportedError(
        f'`GetBOMAndConfigless` is not supported in HWID v{self.HWID_VERSION}')

  def EnumerateHWIDs(self, with_classes: Optional[Set[str]] = None,
                     without_classes: Optional[Set[str]] = None,
                     with_components: Optional[Set[str]] = None,
                     without_components: Optional[Set[str]] = None):
    """Get a filtered set of HWIDs for the given project.

    Args:
      with_classes: Filter for component classes that the HWIDs include.
      without_classes: Filter for component classes that the HWIDs don't
        include.
      with_components: Filter for components that the HWIDs include.
      without_components: Filter for components that the HWIDs don't include.

    Returns:
      A set of HWIDs.

    Raises:
      NotSupportedError: If this function is not supported by the HWID version.
    """
    if (with_classes and without_classes and
        with_classes.intersection(without_classes)):
      raise ValueError(
          'One or more component classes specified for both with and without.')

    if (with_components and without_components and
        with_components.intersection(without_components)):
      raise ValueError(
          'One or more components specified for both with and without.')

    return self._EnumerateHWIDs(with_classes, without_classes, with_components,
                                without_components)

  def _EnumerateHWIDs(self, with_classes: Optional[Set[str]],
                      without_classes: Optional[Set[str]],
                      with_components: Optional[Set[str]],
                      without_components: Optional[Set[str]]):
    """Actual implementation of `EnumerateHWIDs()`."""
    raise NotSupportedError(
        f'`EnumerateHWIDs` is not supported in HWID v{self.HWID_VERSION}')

  def GetComponentClasses(self):
    """Get a set of all component classes for the given project.

    Returns:
      A set of component classes.

    Raises:
      NotSupportedError: If this function is not supported by the HWID version.
    """
    raise NotSupportedError(
        f'`GetComponentsClasses` is not supported in HWID v{self.HWID_VERSION}')

  def GetComponents(self, with_classes: List[Optional[str]] = None):
    """Get a filtered dict of all components for the given project.

    Args:
      with_classes: Filter for component classes that the dict include.

    Returns:
      A dict of components.

    Raises:
      NotSupportedError: If this function is not supported by the HWID version.
    """
    raise NotSupportedError(
        f'`GetComponents` is not supported in HWID v{self.HWID_VERSION}')

  def GetDBV3(self) -> v3_database.Database:
    """Get the `cros.factory.hwid.v3.database.Database` instance if possible.

    Returns:
      The database instance.

    Raises:
      NotSupportedError: If this function is not supported by the HWID version.
    """
    raise NotSupportedError(
        f'`GetDBV3` is not supported in HWID v{self.HWID_VERSION}')

  def GetDBEditableSection(self) -> str:
    """Get the editable section of the HWID DB.

    Returns:
      The text value of the HWID DB editable section.

    Raises:
      NotSupportedError: If this function is not supported by the HWID version.
      HWIDActionError: An error occurs regarding internal data integrity issue.
    """
    raise NotSupportedError(
        f'`GetDBEditableSection` is not supported in HWID v{self.HWID_VERSION}')

  def ReviewDraftDBEditableSection(
      self, draft_db_editable_section,
      derive_fingerprint_only=False) -> DBEditableSectionChangeInfo:
    """Validates the given HWID DB editable section and reports the changes.

    Args:
      draft_db_editable_section: The editable section to review.
      derive_fingerprint_only: Only figure out the fingerprint of the change
          and don't perform any further analysis.

    Returns:
      An instance of `DBEditableSectionChangeInfo` that contains the fingerprint
      of the change as well as some analysis results (only when
      `derive_fingerprint_only=False`) like newly added components.

    Raises:
      NotSupportedError: If this function is not supported by the HWID version.
      HWIDActionError: An error occurs regarding internal data integrity issue.
    """
    raise NotSupportedError(
        '`ReviewDraftDBEditableSection` is not supported in HWID '
        f'v{self.HWID_VERSION}')

  def AnalyzeDraftDBEditableSection(
      self, draft_db_editable_section) -> DBEditableSectionAnalysisReport:
    """Deep analyzes the given HWID DB editable section.

    Args:
      draft_db_editable_section: The editable section to analyze.

    Returns:
      An analysis report including information like line modification status
      and which parts are referring to the same component.

    Raises:
      NotSupportedError: If this function is not supported by the HWID version.
      HWIDActionError: An error occurs regarding internal data integrity issue.
    """
    raise NotSupportedError(
        '`AnalyzeDraftDbEditableSection` is not supported in HWID '
        f'v{self.HWID_VERSION}')

  def GetHWIDBundleResourceInfo(self,
                                fingerprint_only=False) -> BundleResourceInfo:
    """Returns the resource info. to be bundled into the HWID bundle.

    Args:
      fingerprint_only: Specify the method only to calculate the fingerprint
          field of bundle resource info.

    Returns:
      An instance of `BundleResourceInfo` that include everything the bundle
      creation requester need to know to collect external resources.

    Raises:
      NotSupportedError: If this function is not supported by the HWID version.
      HWIDActionError: An error occurs regarding internal data integrity issue.
    """
    raise NotSupportedError(
        '`GetHWIDBundleResourceInfo` is not supported in HWID '
        f'v{self.HWID_VERSION}')

  def BundleHWIDDB(self) -> BundleInfo:
    """Bundles the HWID DB.

    Returns:
      An instance of `BundleInfo` that contains the payload in bytes as well
      as the suggested file name extension.

    Raises:
      NotSupportedError: If this function is not supported by the HWID version.
      HWIDActionError: An error occurs regarding internal data integrity issue.
    """
    raise NotSupportedError(
        f'`BundleHWIDDB` is not supported in HWID v{self.HWID_VERSION}')
