#!/usr/bin/env python3
# Copyright 2013 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

import os
import pickle
import textwrap
import unittest

from cros.factory.hwid.v3 import common
from cros.factory.hwid.v3 import database
from cros.factory.hwid.v3 import rule
from cros.factory.hwid.v3 import yaml_wrapper as yaml
from cros.factory.utils import file_utils


_TEST_DATA_PATH = os.path.join(os.path.dirname(__file__), 'testdata')


def Unordered(data):
  if isinstance(data, dict):
    return {k: Unordered(v)
            for k, v in data.items()}
  if isinstance(data, list):
    return [Unordered(a) for a in data]
  return data


class DatabaseTest(unittest.TestCase):

  def testLoadFile(self):
    database.Database.LoadFile(
        os.path.join(_TEST_DATA_PATH, 'test_database_db.yaml'))
    database.Database.LoadFile(
        os.path.join(_TEST_DATA_PATH, 'test_database_db_bad_checksum.yaml'),
        verify_checksum=False)

    self.assertRaises(
        common.HWIDException, database.Database.LoadFile,
        os.path.join(_TEST_DATA_PATH, 'test_database_db_bad_checksum.yaml'))
    for case in [
        'missing_pattern', 'missing_encoded_field', 'missing_component',
        'missing_encoded_field_bit'
    ]:
      self.assertRaises(
          common.HWIDException, database.Database.LoadFile,
          os.path.join(_TEST_DATA_PATH, 'test_database_db_%s.yaml' % case),
          verify_checksum=False)

  def testLoadInternal(self):
    internal_db = database.Database.LoadFile(
        os.path.join(_TEST_DATA_PATH, 'test_database_db_internal.yaml'))

    self.assertIsInstance(
        internal_db.GetComponents('cls4')['comp6'].values, rule.AVLProbeValue)

    self.assertNotIsInstance(
        internal_db.GetComponents('cls3')['comp5'].values, rule.AVLProbeValue)

  def testSetLinkAVLProbeValue(self):
    db = database.WritableDatabase.LoadFile(
        os.path.join(_TEST_DATA_PATH, 'test_database_db.yaml'))

    db.SetLinkAVLProbeValue('cls4', 'comp7', 'converter-identifier1', True)
    db.SetLinkAVLProbeValue('cls3', 'comp5', 'converter-identifier2', False)

    loaded_db = database.Database.LoadData(
        db.DumpDataWithoutChecksum(internal=True))
    self.assertIsInstance(
        loaded_db.GetComponents('cls4')['comp7'].values, rule.AVLProbeValue)

    self.assertEqual(
        'converter-identifier1',
        loaded_db.GetComponents('cls4')['comp7'].values.converter_identifier)
    self.assertTrue(
        loaded_db.GetComponents('cls4')['comp7'].values.probe_value_matched)

    self.assertEqual(
        'converter-identifier2',
        loaded_db.GetComponents('cls3')['comp5'].values.converter_identifier)
    self.assertFalse(
        loaded_db.GetComponents('cls3')['comp5'].values.probe_value_matched)

  def testSetLinkAVLProbeValue_NoneValue(self):
    db = database.WritableDatabase.LoadFile(
        os.path.join(_TEST_DATA_PATH, 'test_database_db.yaml'))

    db.SetLinkAVLProbeValue('cls4', 'comp8', 'converter-identifier1', False)
    loaded_db = database.Database.LoadData(
        db.DumpDataWithoutChecksum(internal=True))

    values = loaded_db.GetComponents('cls4')['comp8'].values
    self.assertIsInstance(values, rule.AVLProbeValue)
    self.assertEqual('converter-identifier1', values.converter_identifier)
    self.assertFalse(values.probe_value_matched)
    self.assertTrue(values.value_is_none)

  def testSetBundleUUIDs(self):
    db = database.WritableDatabase.LoadFile(
        os.path.join(_TEST_DATA_PATH, 'test_database_db.yaml'))

    db.SetBundleUUIDs('cls4', 'comp7', ['uuid1'])

    loaded_db = database.Database.LoadData(
        db.DumpDataWithoutChecksum(internal=True))
    self.assertCountEqual(
        loaded_db.GetComponents('cls4')['comp7'].bundle_uuids, ['uuid1'])

  def testLoadDump(self):
    db = database.Database.LoadFile(
        os.path.join(_TEST_DATA_PATH, 'test_database_db.yaml'))
    db2 = database.Database.LoadData(db.DumpDataWithoutChecksum())

    self.assertEqual(db, db2)

    db = database.Database.LoadFile(
        os.path.join(_TEST_DATA_PATH, 'test_database_db.yaml'))
    with file_utils.UnopenedTemporaryFile() as path:
      db.DumpFileWithoutChecksum(path)
      database.Database.LoadFile(path, verify_checksum=False)

  def testLoadInternalDumpExternal(self):
    db = database.Database.LoadFile(
        os.path.join(_TEST_DATA_PATH, 'test_database_db_internal.yaml'))
    db2 = database.Database.LoadData(db.DumpDataWithoutChecksum())

    self.assertNotEqual(db, db2)

  def testLoadInternalDumpInternal(self):
    db = database.Database.LoadFile(
        os.path.join(_TEST_DATA_PATH, 'test_database_db_internal.yaml'))
    db2 = database.Database.LoadData(db.DumpDataWithoutChecksum(internal=True))

    self.assertEqual(db, db2)

  def testUpdateComponentNameUnchanged(self):
    db = database.WritableDatabase.LoadFile(
        os.path.join(_TEST_DATA_PATH, 'test_database_db.yaml'))
    db.UpdateComponent('cls4', 'comp6', 'comp6', {
        'field1': 'value1',
        'field2': 'value2'
    }, 'deprecated')
    comps = db.GetComponents('cls4')
    self.assertDictEqual(
        yaml.Dict([('comp6',
                    database.ComponentInfo(
                        values=yaml.Dict([('field1', 'value1'),
                                          ('field2', 'value2')]),
                        status='deprecated')),
                   ('comp7',
                    database.ComponentInfo(
                        values=yaml.Dict([('ggg', 'hhh')]), status='supported',
                        information=yaml.Dict([('comp_group', 'comp6')]))),
                   ('comp8',
                    database.ComponentInfo(values=None, status='supported'))]),
        comps)

  def testUpdateComponentNameChanged(self):
    db = database.WritableDatabase.LoadFile(
        os.path.join(_TEST_DATA_PATH, 'test_database_db.yaml'))
    db.UpdateComponent('cls4', 'comp6', 'comp9', {
        'field1': 'value1',
        'field2': 'value2'
    }, 'deprecated')
    comps = db.GetComponents('cls4')
    self.assertDictEqual(
        yaml.Dict([
            ('comp9',
             database.ComponentInfo(
                 values=yaml.Dict([('field1', 'value1'), ('field2', 'value2')]),
                 status='deprecated')),
            ('comp7',
             database.ComponentInfo(
                 values=yaml.Dict([('ggg', 'hhh')]), status='supported',
                 information=yaml.Dict([('comp_group', 'comp6')]))),
            ('comp8', database.ComponentInfo(values=None, status='supported')),
        ]), comps)
    self.assertEqual({
        0: {
            'cls4': ['comp9']
        },
        1: {
            'cls4': ['comp7']
        }
    }, db.GetEncodedField('field4'))

  def testUpdateComponentNameCollision(self):
    db = database.WritableDatabase.LoadFile(
        os.path.join(_TEST_DATA_PATH, 'test_database_db.yaml'))
    self.assertRaises(common.HWIDException, db.UpdateComponent, 'cls4', 'comp6',
                      'comp7', {
                          'field1': 'value1',
                          'field2': 'value2'
                      }, 'deprecated')

  def testReplaceRules(self):
    db = database.WritableDatabase.LoadFile(
        os.path.join(_TEST_DATA_PATH, 'test_database_db.yaml'))
    db.ReplaceRules([{
        'name': 'device_info.set_image_id',
        'evaluate': "SetImageId('TEST')",
    }])

    self.assertListEqual(
        [rule.Rule('device_info.set_image_id', "SetImageId('TEST')")],
        db.device_info_rules)

  def testDatabasePicklable(self):
    db = database.WritableDatabase.LoadFile(
        os.path.join(_TEST_DATA_PATH, 'test_database_db.yaml'))

    serialized_db = pickle.dumps(db)
    deserialized_db = pickle.loads(serialized_db)

    self.assertEqual(db, deserialized_db)


class ImageIdTest(unittest.TestCase):

  def testExport(self):
    expr = {
        0: 'EVT',
        1: 'DVT',
        2: 'PVT'
    }
    self.assertEqual(
        Unordered(database.ImageId(expr).Export()), {
            0: 'EVT',
            1: 'DVT',
            2: 'PVT'
        })

  def testSetItem(self):
    image_id = database.ImageId({
        0: 'EVT',
        1: 'DVT',
        2: 'PVT'
    })
    image_id[3] = 'XXYYZZ'
    image_id[5] = 'AABBCC'
    self.assertEqual(
        Unordered(image_id.Export()), {
            0: 'EVT',
            1: 'DVT',
            2: 'PVT',
            3: 'XXYYZZ',
            5: 'AABBCC'
        })

    def func(a, b):
      image_id[a] = b

    self.assertRaises(common.HWIDException, func, 3, 'ZZZ')
    self.assertRaises(common.HWIDException, func, 4, 4)
    self.assertRaises(common.HWIDException, func, 'X', 'Y')
    self.assertRaises(common.HWIDException, func, -1, 'Y')

  def testGettingMethods(self):
    image_id = database.ImageId({
        0: 'EVT',
        1: 'DVT',
        2: 'PVT'
    })
    self.assertEqual(image_id.max_image_id, 2)
    self.assertEqual(image_id.rma_image_id, None)
    self.assertEqual(image_id[1], 'DVT')
    self.assertEqual(image_id.GetImageIdByName('EVT'), 0)

    image_id = database.ImageId({
        0: 'EVT',
        1: 'DVT',
        2: 'PVT',
        15: 'RMA'
    })
    self.assertEqual(image_id.max_image_id, 2)
    self.assertEqual(image_id.rma_image_id, 15)
    self.assertEqual(image_id[1], 'DVT')
    self.assertEqual(image_id.GetImageIdByName('EVT'), 0)


class ComponentsTest(unittest.TestCase):

  def testExport(self):
    expr = {
        'cls1': {
            'items': {
                'comp11': {
                    'values': {
                        'p1': 'v1',
                        'p2': 'v2'
                    },
                    'status': 'unsupported'
                }
            }
        },
        'cls2': {
            'items': {
                'comp21': {
                    'values': {
                        'p2': 'v3',
                        'p4': 'v5'
                    },
                    'default': True
                }
            }
        },
        'cls3': {
            'items': {
                'comp31': {
                    'values': None
                },
                'comp41': {
                    'values': {
                        'a': 'b'
                    }
                }
            }
        },
        'cls4': {
            'items': {
                'comp41': {
                    'values': None
                }
            },
            'probeable': False
        }
    }
    c = database.Components(expr)
    self.assertEqual(Unordered(c.Export(True, None)), expr)

  def testExportWithPlaceholders(self):
    expr = {
        'cls1': {
            'items': {
                'comp11': {
                    'values': {
                        'p1': 'v1',
                        'p2': 'v2'
                    },
                    'status': 'unsupported'
                }
            }
        }
    }
    c = database.Components(expr)
    placeholder_opts = database.MagicPlaceholderOptions({
        ('cls1', 'comp11'):
            database.MagicPlaceholderComponentOptions('AAAAA', 'BBBBB')
    })
    self.assertEqual(
        Unordered(c.Export(False, placeholder_opts)), {
            'cls1': {
                'items': {
                    'AAAAA': {
                        'values': {
                            'p1': 'v1',
                            'p2': 'v2'
                        },
                        'status': 'BBBBB'
                    }
                }
            }
        })

  def testSyntaxError(self):
    self.assertRaises(Exception, database.Components, {'cls1': {}})
    self.assertRaises(Exception, database.Components,
                      {'cls1': {
                          'items': {
                              'comp1': {
                                  'status': 'supported'
                              }
                          }
                      }})
    self.assertRaises(Exception, database.Components,
                      {'cls1': {
                          'items': {
                              'comp1': {
                                  'values': {}
                              }
                          }
                      }})
    self.assertRaises(
        Exception, database.Components,
        {'cls1': {
            'items': {
                'comp1': {
                    'values': {
                        'a': 'b'
                    },
                    'status': '???'
                }
            }
        }})

  def testCanEncode(self):
    self.assertTrue(
        database.Components({
            'cls1': {
                'items': {
                    'c1': {
                        'values': {
                            'a': 'b'
                        }
                    }
                }
            }
        }).can_encode)
    self.assertTrue(
        database.Components({
            'cls1': {
                'items': {
                    'c1': {
                        'values': None
                    }
                }
            }
        }).can_encode)

    self.assertTrue(
        database.Components({
            'cls1': {
                'items': {
                    'c1': {
                        'values': {
                            'a': 'b'
                        },
                        'default': True
                    }
                }
            }
        }).can_encode)
    self.assertFalse(
        database.Components({
            'cls1': {
                'items': {
                    'c1': {
                        'values': {
                            'a': 'b'
                        }
                    }
                },
                'probeable': False
            }
        }).can_encode)

    self.assertTrue(
        database.Components({
            'cls1': {
                'items': {
                    'c1': {
                        'values': {
                            'a': 'b'
                        }
                    },
                    # 'c2' is a subset of 'c1', this is allowed, and 'c1' will
                    # have higher priority when encoding.
                    'c2': {
                        'values': {
                            'a': 'b',
                            'x': 'y'
                        }
                    },
                }
            }
        }).can_encode)

    self.assertFalse(
        database.Components({
            'cls1': {
                'items': {
                    'c1': {
                        'values': {
                            'a': 'b'
                        }
                    },
                    'c2': {
                        'values': {
                            'a': 'b'
                        }
                    },
                }
            }
        }).can_encode)
    self.assertTrue(
        database.Components({
            'cls1': {
                'items': {
                    'c1': {
                        'values': {
                            'a': 'b'
                        }
                    },
                    'c2': {
                        'values': {
                            'a': 'b'
                        },
                        'status': 'duplicate'
                    },
                }
            }
        }).can_encode)

  def testAddComponent(self):
    c = database.Components({})
    c.AddComponent('cls1', 'comp1', {
        'a': 'b',
        'c': 'd'
    }, 'supported')
    c.AddComponent('cls1', 'comp2', {
        'a': 'x',
        'c': 'd'
    }, 'unsupported')
    c.AddComponent('cls2', 'comp1', {
        'a': 'b',
        'c': 'd'
    }, 'deprecated')
    c.AddComponent('cls1', 'comp_default', None, 'supported', {
        'comp_group': 'hello',
        'alias': 'alias-comp'
    })
    self.assertEqual(
        Unordered(c.Export(True, None)), {
            'cls1': {
                'items': {
                    'comp1': {
                        'values': {
                            'a': 'b',
                            'c': 'd'
                        }
                    },
                    'comp2': {
                        'values': {
                            'a': 'x',
                            'c': 'd'
                        },
                        'status': 'unsupported'
                    },
                    'comp_default': {
                        'values': None,
                        'information': {
                            'comp_group': 'hello',
                            'alias': 'alias-comp'
                        }
                    }
                }
            },
            'cls2': {
                'items': {
                    'comp1': {
                        'values': {
                            'a': 'b',
                            'c': 'd'
                        },
                        'status': 'deprecated'
                    }
                }
            }
        })

    self.assertRaises(common.HWIDException, c.AddComponent, 'cls1', 'comp1',
                      {'aa': 'bb'}, 'supported')
    c.AddComponent('cls1', 'compX1', {
        'a': 'b',
        'c': 'd'
    }, 'supported')
    self.assertFalse(c.can_encode)

  def testSetComponentStatus(self):
    c = database.Components(
        {'cls1': {
            'items': {
                'comp1': {
                    'values': {
                        'a': 'b'
                    }
                }
            }
        }})
    c.SetComponentStatus('cls1', 'comp1', 'deprecated')
    self.assertEqual(
        Unordered(c.Export(True, None)), {
            'cls1': {
                'items': {
                    'comp1': {
                        'values': {
                            'a': 'b'
                        },
                        'status': 'deprecated'
                    }
                }
            }
        })

  def testGettingMethods(self):
    c = database.Components({
        'cls1': {
            'items': {
                'comp1': {
                    'values': {
                        'a': 'b'
                    },
                    'status': 'unqualified'
                },
                'comp2': {
                    'values': {
                        'a': 'c'
                    }
                }
            }
        },
        'cls2': {
            'items': {
                'comp3': {
                    'values': {
                        'x': 'y'
                    }
                },
                'comp4': {
                    'values': {
                        'c': 'd'
                    },
                    'information': {
                        'comp_group': 'comp5',
                        'alias': 'cls2_vendor_a-part-number'
                    }
                }
            }
        }
    })
    self.assertEqual(sorted(c.component_classes), ['cls1', 'cls2'])
    self.assertEqual(len(c.GetComponents('cls1')), 2)
    self.assertEqual(sorted(c.GetComponents('cls1').keys()), ['comp1', 'comp2'])
    self.assertEqual(c.GetComponents('cls1')['comp1'].values, {'a': 'b'})
    self.assertEqual(c.GetComponents('cls1')['comp1'].status, 'unqualified')
    self.assertEqual(c.GetComponents('cls1')['comp2'].values, {'a': 'c'})
    self.assertEqual(c.GetComponents('cls1')['comp2'].status, 'supported')

    self.assertEqual(len(c.GetComponents('cls2')), 2)
    self.assertDictEqual(
        c.GetComponents('cls2')['comp4'].information, {
            'comp_group': 'comp5',
            'alias': 'cls2_vendor_a-part-number'
        })

  def testExportComponentInfoDictOrder(self):
    c = database.ComponentInfo(
        values=yaml.Dict([
            ('field1', 'val1'),
            ('field3', 'val3'),
            ('field2', 'val2'),
            ('field4', 'val4'),
        ]), status='unqualified', information=yaml.Dict([
            ('info3', 'val3'),
            ('info2', 'val2'),
            ('info1', 'val1'),
            ('info4', 'val4'),
        ]))

    order_preserved = yaml.safe_dump(c.Export(), default_flow_style=False)
    order_by_key = yaml.safe_dump(
        c.Export(sort_values_by_key=True), default_flow_style=False)

    self.assertEqual(
        textwrap.dedent('''\
            status: unqualified
            values:
              field1: val1
              field3: val3
              field2: val2
              field4: val4
            information:
              info3: val3
              info2: val2
              info1: val1
              info4: val4
    '''), order_preserved)
    self.assertEqual(
        textwrap.dedent('''\
            status: unqualified
            values:
              field1: val1
              field2: val2
              field3: val3
              field4: val4
            information:
              info1: val1
              info2: val2
              info3: val3
              info4: val4
    '''), order_by_key)

  def testGetComponentNameByHash(self):
    c = database.Components({
        'cls1': {
            'items': {
                'comp1': {
                    'values': {
                        'digits': '1234',
                        'a': 'b',
                        'c': 'd',
                    },
                    'status': 'unqualified'
                },
                'comp2': {
                    'values': {
                        'a': 'c'
                    }
                }
            }
        },
        'cls2': {
            'items': {
                'comp3': {
                    'values': None,
                },
                'comp4': {
                    'values': {
                        'regex': rule.Value('abc.*', is_re=True),
                    },
                    'information': {
                        'comp_group': 'comp5',
                        'alias': 'cls2_vendor_a-part-number'
                    }
                }
            }
        },
    })
    comp1_hash = database.ComponentInfo(
        values={
            'a': 'b',
            'c': 'd',
            'digits': '1234',
        }, status='unqualified').comp_hash
    comp2_hash = database.ComponentInfo(values={
        'a': 'c'
    }, status='supported').comp_hash
    comp3_hash = database.ComponentInfo(values=None,
                                        status='supported').comp_hash
    comp4_hash = database.ComponentInfo(
        values={
            'regex': rule.Value('abc.*', is_re=True)
        }, status='supported', information={
            'alias': 'cls2_vendor_a-part-number',
            'comp_group': 'comp5',
        }).comp_hash

    self.assertEqual('comp1', c.GetComponentNameByHash('cls1', comp1_hash))
    self.assertEqual('comp2', c.GetComponentNameByHash('cls1', comp2_hash))
    self.assertEqual('comp3', c.GetComponentNameByHash('cls2', comp3_hash))
    self.assertEqual('comp4', c.GetComponentNameByHash('cls2', comp4_hash))

  def testComponentHashOrderIrrelevant(self):
    comp = database.ComponentInfo(
        yaml.Dict([
            ('a1', 'b1'),
            ('a2', 'b2'),
            ('a3', 'b3'),
        ]), status='unqualified')
    comp_values_reversed = database.ComponentInfo(
        yaml.Dict([
            ('a3', 'b3'),
            ('a2', 'b2'),
            ('a1', 'b1'),
        ]), status='unqualified')

    self.assertEqual(comp.comp_hash, comp_values_reversed.comp_hash)

  def testComponentHashUnique(self):
    comp = database.ComponentInfo(
        yaml.Dict([
            ('a1', 'b1'),
            ('a2', 'b2'),
            ('a3', 'b3'),
        ]), status='supported')
    comp_diff = database.ComponentInfo(
        yaml.Dict([
            ('a3', 'b3'),
            ('a2', 'b2'),
            ('a1', 'c1'),
        ]), status='supported')

    self.assertNotEqual(comp.comp_hash, comp_diff.comp_hash)

  def testUpdateComponent_MappingUpdate(self):

    c = database.Components({
        'cls1': {
            'items': {
                'comp1': {
                    'values': {
                        'digits': '1234',
                        'a': 'b',
                        'c': 'd',
                    },
                    'status': 'unqualified'
                },
                'comp2': {
                    'values': {
                        'a': 'c'
                    }
                }
            }
        }
    })
    old_comp1_hash = database.ComponentInfo(
        values={
            'a': 'b',
            'c': 'd',
            'digites': '1234',
        }, status='unqualified').comp_hash
    new_comp1_hash = database.ComponentInfo(values=None,
                                            status='unsupported').comp_hash
    old_comp2_hash = database.ComponentInfo(values={
        'a': 'c'
    }, status='supported').comp_hash
    new_comp2_hash = database.ComponentInfo(
        values={
            'regex': rule.Value('abc.*', is_re=True)
        }, status='unsupported', information={
            'alias': 'cls2_vendor_a-part-number',
            'comp_group': 'comp5',
        }).comp_hash

    c.UpdateComponent(comp_cls='cls1', old_name='comp1',
                      new_name='comp1_renamed', values=None,
                      support_status='unsupported')
    # Update in-place.
    c.UpdateComponent(
        comp_cls='cls1', old_name='comp2', new_name='comp2', values={
            'regex': rule.Value('abc.*', is_re=True),
        }, support_status='unsupported', information={
            'comp_group': 'comp5',
            'alias': 'cls2_vendor_a-part-number'
        })

    # Old hash values in mapping should be removed.
    self.assertRaises(KeyError, c.GetComponentNameByHash, 'cls1',
                      old_comp1_hash)
    self.assertRaises(KeyError, c.GetComponentNameByHash, 'cls1',
                      old_comp2_hash)
    # New hash values are updated.
    self.assertEqual('comp1_renamed',
                     c.GetComponentNameByHash('cls1', new_comp1_hash))
    self.assertEqual('comp2', c.GetComponentNameByHash('cls1', new_comp2_hash))

  def testSetComponentStatus_MappingUpdate(self):

    c = database.Components({
        'cls1': {
            'items': {
                'comp1': {
                    'values': {
                        'digits': '1234',
                        'a': 'b',
                        'c': 'd',
                    },
                    'status': 'unqualified'
                },
                'comp2': {
                    'values': {
                        'a': 'c'
                    }
                }
            }
        }
    })
    old_comp1_hash = database.ComponentInfo(
        values={
            'a': 'b',
            'c': 'd',
            'digits': '1234',
        }, status='unqualified').comp_hash
    new_comp1_hash = database.ComponentInfo(
        values={
            'a': 'b',
            'c': 'd',
            'digits': '1234',
        }, status='unsupported').comp_hash

    c.SetComponentStatus(comp_cls='cls1', comp_name='comp1',
                         status='unsupported')

    # Old hash in mapping should be removed.
    self.assertRaises(KeyError, c.GetComponentNameByHash, 'cls1',
                      old_comp1_hash)
    self.assertEqual('comp1', c.GetComponentNameByHash('cls1', new_comp1_hash))


class EncodedFieldsTest(unittest.TestCase):

  def testExport(self):
    expr = {
        'aaa': {
            0: {
                'x': [],
                'y': 'y',
                'z': ['z1', 'z2']
            },
            1: {
                'x': 'xx',
                'y': [],
                'z': []
            }
        },
        'bbb': {
            0: {
                'b': ['b1', 'b2', 'b3']
            }
        }
    }
    encoded_fields = database.EncodedFields(expr)
    self.assertEqual(Unordered(encoded_fields.Export(None)), expr)

    expr = {
        'aaa': {
            0: {
                'x': [],
                'y': 'y',
                'z': ['z1', 'z2']
            },
            2: {
                'x': 'xx',
                'y': [],
                'z': []
            }
        }
    }
    encoded_fields = database.EncodedFields(expr)
    self.assertEqual(Unordered(encoded_fields.Export(None)), expr)

  def testExportWithPlaceholders(self):
    expr = {
        'aaa': {
            0: {
                'x': [],
                'y': 'y',
                'z': ['z1', 'z2']
            },
            1: {
                'x': 'xx',
                'y': [],
                'z': []
            }
        },
        'bbb': {
            0: {
                'b': ['b1', 'b2', 'b3']
            }
        }
    }
    encoded_fields = database.EncodedFields(expr)
    placeholder_options = database.MagicPlaceholderOptions({
        ('x', 'xx'): database.MagicPlaceholderComponentOptions('@@xx@@', None),
        ('b', 'b1'): database.MagicPlaceholderComponentOptions('@@b1@@', None),
    })
    self.assertEqual(
        Unordered(encoded_fields.Export(placeholder_options)), {
            'aaa': {
                0: {
                    'x': [],
                    'y': 'y',
                    'z': ['z1', 'z2']
                },
                1: {
                    'x': '@@xx@@',
                    'y': [],
                    'z': []
                }
            },
            'bbb': {
                0: {
                    'b': ['@@b1@@', 'b2', 'b3']
                }
            }
        })

    expr = {
        'aaa': {
            0: {
                'x': [],
                'y': 'y',
                'z': ['z1', 'z2']
            },
            2: {
                'x': 'xx',
                'y': [],
                'z': []
            }
        }
    }
    encoded_fields = database.EncodedFields(expr)
    self.assertEqual(Unordered(encoded_fields.Export(None)), expr)

  def testSyntaxError(self):
    self.assertRaises(Exception, database.EncodedFields,
                      {'a': {
                          'bad_index': {
                              'a': None
                          }
                      }})
    self.assertRaises(Exception, database.EncodedFields, {'a': {
        0: {}
    }})
    self.assertRaises(Exception, database.EncodedFields,
                      {'a': {
                          0: {
                              'a': '3'
                          },
                          1: {
                              'c': '9'
                          }
                      }})

  def testCannotEncode(self):
    self.assertFalse(
        database.EncodedFields({
            'a': {
                0: {
                    'a': '3'
                },
                1: {
                    'a': '3'
                }
            }
        }).can_encode)

  def testAddFieldComponents(self):
    e = database.EncodedFields({'e1': {
        0: {
            'a': 'A',
            'b': 'B'
        }
    }})
    e.AddFieldComponents('e1', {
        'a': ['AA'],
        'b': ['BB']
    })
    e.AddFieldComponents('e1', {
        'a': ['AA', 'AX'],
        'b': ['BB']
    })

    self.assertEqual(
        Unordered(e.Export(None)), {
            'e1': {
                0: {
                    'a': 'A',
                    'b': 'B'
                },
                1: {
                    'a': 'AA',
                    'b': 'BB'
                },
                2: {
                    'a': ['AA', 'AX'],
                    'b': 'BB'
                }
            }
        })

    # `e1` should encode only component class `a` and `b`.
    self.assertRaises(common.HWIDException, e.AddFieldComponents, 'e1', {
        'c': ['CC'],
        'a': ['AAAAAA'],
        'b': ['BB']
    })

  def testAddNewField(self):
    e = database.EncodedFields({'e1': {
        0: {
            'a': 'A',
            'b': 'B'
        }
    }})
    e.AddNewField('e2', {
        'c': ['CC'],
        'd': ['DD']
    })

    self.assertEqual(
        Unordered(e.Export(None)), {
            'e1': {
                0: {
                    'a': 'A',
                    'b': 'B'
                }
            },
            'e2': {
                0: {
                    'c': 'CC',
                    'd': 'DD'
                }
            }
        })

    # `e2` already exists.
    self.assertRaises(common.HWIDException, e.AddNewField, 'e2',
                      {'xxx': ['yyy']})
    self.assertRaises(common.HWIDException, e.AddNewField, 'e3', {})

  def testGettingMethods(self):
    e = database.EncodedFields({
        'e1': {
            0: {
                'a': 'A',
                'b': 'B'
            },
            1: {
                'a': ['AA', 'AAA'],
                'b': 'B'
            }
        },
        'e2': {
            0: {
                'c': None,
                'd': []
            },
            2: {
                'c': ['C2', 'C1', 'C3'],
                'd': 'D'
            }
        }
    })
    self.assertEqual(set(e.encoded_fields), set(['e1', 'e2']))
    self.assertEqual(
        e.GetField('e1'), {
            0: {
                'a': ['A'],
                'b': ['B']
            },
            1: {
                'a': ['AA', 'AAA'],
                'b': ['B']
            }
        })
    self.assertEqual(
        e.GetField('e2'), {
            0: {
                'c': [],
                'd': []
            },
            2: {
                'c': ['C1', 'C2', 'C3'],
                'd': ['D']
            }
        })
    self.assertEqual(e.GetComponentClasses('e1'), {'a', 'b'})
    self.assertEqual(e.GetComponentClasses('e2'), {'c', 'd'})
    self.assertEqual(e.GetFieldForComponent('c'), 'e2')
    self.assertEqual(e.GetFieldForComponent('x'), None)


class PatternTest(unittest.TestCase):

  def testExport(self):
    expr = [{
        'image_ids': [1, 2],
        'encoding_scheme': 'base32',
        'fields': [{
            'aaa': 1
        }, {
            'ccc': 2
        }]
    }, {
        'image_ids': [3],
        'encoding_scheme': 'base8192',
        'fields': []
    }]
    pattern = database.Pattern(expr)
    self.assertEqual(Unordered(pattern.Export()), expr)

  def testGetImageId(self):
    expr = [{
        'image_ids': [1, 2],
        'encoding_scheme': 'base32',
        'fields': [{
            'aaa': 1
        }, {
            'ccc': 2
        }]
    }, {
        'image_ids': [15],
        'encoding_scheme': 'base8192',
        'fields': []
    }]
    pattern = database.Pattern(expr)
    # pylint: disable=protected-access
    self.assertEqual(pattern._max_image_id, 2)

  def testSyntaxError(self):
    # missing "image_ids" field
    self.assertRaises(Exception, database.Pattern, [{
        'image_id': [3],
        'encoding_scheme': 'base32',
        'fields': []
    }])

    # extra field "extra"
    self.assertRaises(Exception, database.Pattern, [{
        'image_ids': [3],
        'extra': 'xxx',
        'encoding_scheme': 'base32',
        'fields': []
    }])
    self.assertRaises(Exception, database.Pattern, [{
        'image_ids': [],
        'encoding_scheme': 'base32',
        'fields': []
    }])

    # encoding scheme is either "base32" or "base8192"
    self.assertRaises(Exception, database.Pattern, [{
        'image_ids': [3],
        'encoding_scheme': 'base31',
        'fields': []
    }])

    self.assertRaises(Exception, database.Pattern, [{
        'image_ids': [3],
        'encoding_scheme': 'base32',
        'fields': [{
            'aaa': -1
        }]
    }])

    # value of the "fields" field should be a list of dict of size 1
    self.assertRaises(Exception, database.Pattern, [{
        'image_ids': [3],
        'encoding_scheme': 'base32',
        'fields': [{
            'aaa': 3,
            'bbb': 4
        }]
    }])

  def testAddEmptyPattern(self):
    pattern = database.Pattern([{
        'image_ids': [0],
        'encoding_scheme': 'base32',
        'fields': []
    }])

    associated_pattern_idx = pattern.AddEmptyPattern(2, 'base8192')

    self.assertEqual(1, associated_pattern_idx)
    self.assertEqual(
        Unordered(pattern.Export()), [{
            'image_ids': [0],
            'encoding_scheme': 'base32',
            'fields': []
        }, {
            'image_ids': [2],
            'encoding_scheme': 'base8192',
            'fields': []
        }])
    self.assertEqual(pattern.GetEncodingScheme(), 'base8192')

    # Image id `2` already exists.
    self.assertRaises(common.HWIDException, pattern.AddEmptyPattern, 2,
                      'base8192')

  def testAddImageIdTo(self):
    pattern = database.Pattern([{
        'image_ids': [0],
        'encoding_scheme': 'base32',
        'fields': []
    }, {
        'image_ids': [2],
        'encoding_scheme': 'base32',
        'fields': []
    }])

    associated_pattern_idx = pattern.AddImageId(3, reference_image_id=0)

    self.assertEqual(0, associated_pattern_idx)
    self.assertEqual(
        Unordered(pattern.Export()), [{
            'image_ids': [0, 3],
            'encoding_scheme': 'base32',
            'fields': []
        }, {
            'image_ids': [2],
            'encoding_scheme': 'base32',
            'fields': []
        }])

    associated_pattern_idx = pattern.AddImageId(4, pattern_idx=1)

    self.assertEqual(1, associated_pattern_idx)
    self.assertEqual(
        Unordered(pattern.Export()), [{
            'image_ids': [0, 3],
            'encoding_scheme': 'base32',
            'fields': []
        }, {
            'image_ids': [2, 4],
            'encoding_scheme': 'base32',
            'fields': []
        }])

    # `reference_image_id` should exist.
    self.assertRaisesRegex(common.HWIDException, r'No pattern for image id 1\.',
                           pattern.AddImageId, 5, reference_image_id=1)

    # New `image_id` already exists.
    self.assertRaisesRegex(common.HWIDException,
                           r'The image id 0 has already been in used\.',
                           pattern.AddImageId, 0, reference_image_id=3)

    # No such pattern at the index.
    self.assertRaisesRegex(common.HWIDException,
                           r'No such pattern at position 2\.',
                           pattern.AddImageId, 5, pattern_idx=2)

  def testAppendField(self):
    pattern = database.Pattern([{
        'image_ids': [0],
        'encoding_scheme': 'base32',
        'fields': []
    }])

    pattern.AppendField('aaa', 3)
    pattern.AppendField('bbb', 0)
    pattern.AppendField('aaa', 1)
    self.assertEqual(
        Unordered(pattern.Export()), [{
            'image_ids': [0],
            'encoding_scheme': 'base32',
            'fields': [{
                'aaa': 3
            }, {
                'bbb': 0
            }, {
                'aaa': 1
            }]
        }])

  def testGettingMethods(self):
    pattern = database.Pattern([{
        'image_ids': [0],
        'encoding_scheme': 'base32',
        'fields': [{
            'a': 3
        }, {
            'b': 0
        }, {
            'a': 1
        }, {
            'c': 5
        }]
    }])

    self.assertEqual(pattern.GetTotalBitLength(), 9)
    self.assertEqual(pattern.GetFieldsBitLength(), {
        'a': 4,
        'b': 0,
        'c': 5
    })
    self.assertEqual(pattern.GetBitMapping(), [('a', 2), ('a', 1), ('a', 0),
                                               ('a', 3), ('c', 4), ('c', 3),
                                               ('c', 2), ('c', 1), ('c', 0)])
    self.assertEqual(
        pattern.GetBitMapping(max_bit_length=7), [('a', 2), ('a', 1), ('a', 0),
                                                  ('a', 3), ('c', 2), ('c', 1),
                                                  ('c', 0)])

  def testPatternCount(self):
    pattern_0 = {
        'image_ids': [0, 1, 2],
        'encoding_scheme': 'base32',
        'fields': [{
            'a': 3
        }, {
            'b': 0
        }, {
            'a': 1
        }, {
            'c': 5
        }]
    }
    pattern_1 = {
        'image_ids': [3],
        'encoding_scheme': 'base32',
        'fields': [{
            'a': 3
        }, {
            'b': 0
        }]
    }
    patterns = database.Pattern([pattern_0, pattern_1])
    self.assertEqual(2, patterns.num_patterns)

    # Add new image id with a new pattern.
    associated_pattern_idx = patterns.AddEmptyPattern(
        4, common.ENCODING_SCHEME.base8192)

    self.assertEqual(2, associated_pattern_idx)

    # Add new image id and reuse an existing pattern.
    associated_pattern_idx = patterns.AddImageId(5, reference_image_id=1)

    self.assertEqual(0, associated_pattern_idx)

  def testGetPattern(self):
    pattern_0 = {
        'image_ids': [0, 1, 2],
        'encoding_scheme': 'base32',
        'fields': [{
            'a': 3
        }, {
            'b': 0
        }, {
            'a': 1
        }, {
            'c': 5
        }]
    }

    pattern_1 = {
        'image_ids': [3],
        'encoding_scheme': 'base32',
        'fields': [{
            'a': 3
        }, {
            'b': 0
        }]
    }

    pattern_datum_0 = database.PatternDatum(0, common.ENCODING_SCHEME.base32, [
        database.PatternField('a', 3),
        database.PatternField('b', 0),
        database.PatternField('a', 1),
        database.PatternField('c', 5),
    ])
    pattern_datum_1 = database.PatternDatum(1, common.ENCODING_SCHEME.base32, [
        database.PatternField('a', 3),
        database.PatternField('b', 0),
    ])

    patterns = database.Pattern([pattern_0, pattern_1])
    self.assertEqual(pattern_datum_0, patterns.GetPattern(image_id=0))
    self.assertEqual(pattern_datum_1, patterns.GetPattern(image_id=3))

    self.assertEqual(pattern_datum_0, patterns.GetPattern(pattern_idx=0))
    self.assertEqual(pattern_datum_1, patterns.GetPattern(pattern_idx=1))


class RulesTest(unittest.TestCase):

  def testNormal(self):
    rules = database.Rules([{
        'name': 'verify.1',
        'evaluate': 'a = 3',
        'when': 'True'
    }, {
        'name': 'device_info.1',
        'evaluate': ['a = 3', 'b = 5']
    }, {
        'name': 'verify.2',
        'evaluate': 'c = 7',
        'when': 'True',
        'otherwise': 'False'
    }])

    self.assertEqual(len(rules.verify_rules), 2)
    self.assertEqual(rules.verify_rules[0].ExportToDict(), {
        'name': 'verify.1',
        'evaluate': 'a = 3',
        'when': 'True'
    })
    self.assertEqual(
        rules.verify_rules[1].ExportToDict(), {
            'name': 'verify.2',
            'evaluate': 'c = 7',
            'when': 'True',
            'otherwise': 'False'
        })

    self.assertEqual(len(rules.device_info_rules), 1)
    self.assertEqual(rules.device_info_rules[0].ExportToDict(), {
        'name': 'device_info.1',
        'evaluate': ['a = 3', 'b = 5']
    })

  def testAddDeviceInfoRule(self):
    rules = database.Rules([])
    rules.AddDeviceInfoRule('rule1', 'eval1')
    rules.AddDeviceInfoRule('rule3', 'eval3')
    rules.AddDeviceInfoRule('rule2', 'eval2', position=1)
    rules.AddDeviceInfoRule('rule0', 'eval0', position=0)
    self.assertEqual(
        Unordered(rules.Export()), [{
            'name': 'device_info.rule0',
            'evaluate': 'eval0'
        }, {
            'name': 'device_info.rule1',
            'evaluate': 'eval1'
        }, {
            'name': 'device_info.rule2',
            'evaluate': 'eval2'
        }, {
            'name': 'device_info.rule3',
            'evaluate': 'eval3'
        }])

  def testSyntaxError(self):
    self.assertRaises(Exception, database.Rules, 'abc')

    # Missing "name", "evaluate".
    self.assertRaises(Exception, database.Rules, [{
        'namr': '123'
    }])

    # The prefix of the value of name should be either "verify." or
    # "device_info."
    self.assertRaises(Exception, database.Rules, [{
        'name': 'xxx',
        'evaluate': 'a'
    }])


if __name__ == '__main__':
  unittest.main()
