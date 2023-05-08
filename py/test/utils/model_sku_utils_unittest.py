#!/usr/bin/env python3
# Copyright 2020 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

import unittest
from unittest import mock

from cros.factory.test.utils import model_sku_utils


class TestModelSKUUtils(unittest.TestCase):
  """Unit tests for model_sku_utils."""

  @classmethod
  def _SetProjectConfigMock(cls, listdir_mock, load_config_mock):
    """Mock a project config database."""
    listdir_mock.return_value = [
        'program1_project1_model_sku.json',
        'program1_project2_model_sku.json',
        'program2_project3_model_sku.json',
        'program2_project4_model_sku.json',
        'program3_project5_model_sku.json',
    ]
    load_config_mock.side_effect = [{
        'model': {
            'design1': {
                'has_laser': True
            },
            'design2': {
                'has_laser': False
            }
        },
        'product_sku': {
            'Fakeproduct': {
                '6': {
                    'fw_config': 121
                }
            }
        },
        'oem_name': {
            'design1': {
                '': 'FAKE_OEM',
            },
            'design2': {
                'loema': 'FAKE_OEMA',
            },
        },
    }, {
        'model': {
            'design3': {
                'has_laser': True
            },
            'design4': {
                'has_laser': False
            }
        },
        'product_sku': {
            'Fakeproduct': {
                '7': {
                    'fw_config': 122
                }
            }
        },
    }, {
        'model': {
            'design5': {
                'has_laser': True
            },
            'design6': {
                'has_laser': False
            }
        },
        'product_sku': {
            'fake,cool,rev0': {
                '8': {
                    'fw_config': 123
                }
            }
        },
        'oem_name': {
            'design5': {
                '': 'FAKE_OEMB',
            },
        },
    }, {
        'model': {
            'design7': {
                'has_laser': True
            },
            'design8': {
                'has_laser': False
            }
        },
        'product_sku': {
            'fake,hao,rev123': {
                '9': {
                    'fw_config': 124
                }
            }
        },
        'oem_name': {
            'design8': {
                'loemc': 'FAKE_LOEMC',
            },
        },
    }, {
        'model': {
            'design10': {
                'has_laser': True
            },
            'design11': {
                'has_laser': False
            }
        },
        'product_sku': {
            'design10': {
                '10': {
                    'fw_config': 125
                }
            }
        },
        'oem_name': {
            'design10': {
                '': 'FAKE_OEM',
            },
            'design11': {
                'loema': 'FAKE_OEMA',
            },
        },
    }]

  @classmethod
  def _SetCrosConfigMock(cls, cros_config_mock, sku_id, model,
                         custom_label_tag):
    """Mock cros_config."""
    # Constructor returns itself
    cros_config_mock.return_value = cros_config_mock
    cros_config_mock.GetSkuID.return_value = sku_id
    cros_config_mock.GetModelName.return_value = model
    cros_config_mock.GetCustomLabelTag.return_value = (not custom_label_tag,
                                                       custom_label_tag)

  @mock.patch('os.listdir')
  @mock.patch('cros.factory.external.chromeos_cli.cros_config.CrosConfig')
  @mock.patch('cros.factory.utils.config_utils.LoadConfig')
  @mock.patch('cros.factory.utils.sys_interface.SystemInterface')
  def testGetDesignConfigX86(self, sys_mock, load_config_mock, cros_config_mock,
                             listdir_mock):
    """Test GetDesignConfig on X86 devices."""
    sys_mock.ReadFile.return_value = 'Fakeproduct'
    self._SetCrosConfigMock(cros_config_mock, '6', 'design1', None)
    self._SetProjectConfigMock(listdir_mock, load_config_mock)
    design_config = model_sku_utils.GetDesignConfig(sys_mock)
    self.assertEqual(design_config['fw_config'], 121)
    self.assertEqual(design_config['program'], 'program1')
    self.assertEqual(design_config['project'], 'project1')
    self.assertEqual(design_config['has_laser'], True)
    self.assertEqual(design_config['oem_name'], 'FAKE_OEM')

    sys_mock.ReadFile.return_value = 'Fakeproduct'
    self._SetCrosConfigMock(cros_config_mock, '6', 'design2', None)
    self._SetProjectConfigMock(listdir_mock, load_config_mock)
    design_config = model_sku_utils.GetDesignConfig(sys_mock)
    self.assertEqual(design_config['fw_config'], 121)
    self.assertEqual(design_config['program'], 'program1')
    self.assertEqual(design_config['project'], 'project1')
    self.assertEqual(design_config['has_laser'], False)
    self.assertNotIn('oem_name', design_config)

    sys_mock.ReadFile.return_value = 'Fakeproduct'
    self._SetCrosConfigMock(cros_config_mock, '7', 'design3', None)
    self._SetProjectConfigMock(listdir_mock, load_config_mock)
    design_config = model_sku_utils.GetDesignConfig(sys_mock)
    self.assertEqual(design_config['fw_config'], 122)
    self.assertEqual(design_config['program'], 'program1')
    self.assertEqual(design_config['project'], 'project2')
    self.assertEqual(design_config['has_laser'], True)
    self.assertNotIn('oem_name', design_config)

    sys_mock.ReadFile.return_value = 'Fakeproduct'
    self._SetCrosConfigMock(cros_config_mock, '7', 'design4', 'loemb')
    self._SetProjectConfigMock(listdir_mock, load_config_mock)
    design_config = model_sku_utils.GetDesignConfig(sys_mock)
    self.assertEqual(design_config['fw_config'], 122)
    self.assertEqual(design_config['program'], 'program1')
    self.assertEqual(design_config['project'], 'project2')
    self.assertEqual(design_config['has_laser'], False)
    self.assertNotIn('oem_name', design_config)

    sys_mock.ReadFile.return_value = 'Virtualproduct'
    self._SetCrosConfigMock(cros_config_mock, '7', 'design0', None)
    self._SetProjectConfigMock(listdir_mock, load_config_mock)
    design_config = model_sku_utils.GetDesignConfig(sys_mock)
    self.assertEqual(design_config, {})

    sys_mock.ReadFile.return_value = 'Fakeproduct'
    self._SetCrosConfigMock(cros_config_mock, '10', 'design10', None)
    self._SetProjectConfigMock(listdir_mock, load_config_mock)
    design_config = model_sku_utils.GetDesignConfig(sys_mock)
    self.assertEqual(design_config['fw_config'], 125)
    self.assertEqual(design_config['program'], 'program3')
    self.assertEqual(design_config['project'], 'project5')
    self.assertEqual(design_config['has_laser'], True)
    self.assertEqual(design_config['oem_name'], 'FAKE_OEM')

  @mock.patch('os.listdir')
  @mock.patch('cros.factory.external.chromeos_cli.cros_config.CrosConfig')
  @mock.patch('cros.factory.utils.config_utils.LoadConfig')
  @mock.patch('cros.factory.utils.sys_interface.SystemInterface')
  def testGetDesignConfigARM(self, sys_mock, load_config_mock, cros_config_mock,
                             listdir_mock):
    """Test GetDesignConfig on ARM devices."""
    sys_mock.ReadFile.side_effect = [
        # Read from PRODUCT_NAME_PATH and fail.
        Exception(),
        # Read from DEVICE_TREE_COMPATIBLE_PATH.
        'fake,hao,rev123\0fake,cool,rev0'
    ]
    self._SetCrosConfigMock(cros_config_mock, '8', 'design5', None)
    self._SetProjectConfigMock(listdir_mock, load_config_mock)
    design_config = model_sku_utils.GetDesignConfig(sys_mock)
    self.assertEqual(design_config['fw_config'], 123)
    self.assertEqual(design_config['program'], 'program2')
    self.assertEqual(design_config['project'], 'project3')
    self.assertEqual(design_config['has_laser'], True)
    self.assertEqual(design_config['oem_name'], 'FAKE_OEMB')

    sys_mock.ReadFile.side_effect = [
        # Read from PRODUCT_NAME_PATH and fail.
        Exception(),
        # Read from DEVICE_TREE_COMPATIBLE_PATH.
        'fake,hao,rev123\0fake,cool,rev0'
    ]
    self._SetCrosConfigMock(cros_config_mock, '8', 'design6', None)
    self._SetProjectConfigMock(listdir_mock, load_config_mock)
    design_config = model_sku_utils.GetDesignConfig(sys_mock)
    self.assertEqual(design_config['fw_config'], 123)
    self.assertEqual(design_config['program'], 'program2')
    self.assertEqual(design_config['project'], 'project3')
    self.assertEqual(design_config['has_laser'], False)
    self.assertNotIn('oem_name', design_config)

    sys_mock.ReadFile.side_effect = [
        # Read from PRODUCT_NAME_PATH and fail.
        Exception(),
        # Read from DEVICE_TREE_COMPATIBLE_PATH.
        'fake,hao,rev123\0fake,cool,rev0'
    ]
    self._SetCrosConfigMock(cros_config_mock, '9', 'design8', 'loemc')
    self._SetProjectConfigMock(listdir_mock, load_config_mock)
    design_config = model_sku_utils.GetDesignConfig(sys_mock)
    self.assertEqual(design_config['fw_config'], 124)
    self.assertEqual(design_config['program'], 'program2')
    self.assertEqual(design_config['project'], 'project4')
    self.assertEqual(design_config['has_laser'], False)
    self.assertEqual(design_config['oem_name'], 'FAKE_LOEMC')

    sys_mock.ReadFile.side_effect = [
        # Read from PRODUCT_NAME_PATH and fail.
        Exception(),
        # Read from DEVICE_TREE_COMPATIBLE_PATH.
        'fake,bad,rev123\0fake,boo,rev0'
    ]
    self._SetCrosConfigMock(cros_config_mock, '9', 'design9', None)
    self._SetProjectConfigMock(listdir_mock, load_config_mock)
    design_config = model_sku_utils.GetDesignConfig(sys_mock)
    self.assertEqual(design_config, {})

    sys_mock.ReadFile.side_effect = [
        # Read from PRODUCT_NAME_PATH and fail.
        Exception(),
        # Read from DEVICE_TREE_COMPATIBLE_PATH.
        'fake,bad,rev123\0fake,boo,rev0'
    ]
    self._SetCrosConfigMock(cros_config_mock, '10', 'design10', None)
    self._SetProjectConfigMock(listdir_mock, load_config_mock)
    design_config = model_sku_utils.GetDesignConfig(sys_mock)
    self.assertEqual(design_config['fw_config'], 125)
    self.assertEqual(design_config['program'], 'program3')
    self.assertEqual(design_config['project'], 'project5')
    self.assertEqual(design_config['has_laser'], True)
    self.assertEqual(design_config['oem_name'], 'FAKE_OEM')


if __name__ == '__main__':
  unittest.main()
