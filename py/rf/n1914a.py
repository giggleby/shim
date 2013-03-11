# Copyright (c) 2013 The Chromium OS Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.


'''
Implementation for Agilent EPM Series Power Meter (N1914A) device.

Because N1914A enables up to 4 ports, methods in this class default to
expose a parameter called port to specify where action will take place.
'''


import struct

import factory_common  # pylint: disable=W0611
from cros.factory.rf.agilent_scpi import AgilentSCPI
from cros.factory.rf.lan_scpi import Error


class N1914A(AgilentSCPI):
  '''
  An Agilent EPM Series Power Meter (N1914A) device.
  '''
  def __init__(self, *args, **kwargs):
    super(N1914A, self).__init__('N1914A', *args, **kwargs)
    self.timeout = 20  # Weak power will cause a relatively long run.

  # Format related methods.
  def SetAsciiFormat(self):
    '''Sets the numeric data transferred over SCPI to ASCII.'''
    self.Send('FORM ASCii')

  def SetRealFormat(self):
    '''Sets the numeric data transferred over SCPI to binary.'''
    self.Send('FORM REAL')

  # Sampling setting related methods.
  def ToNormalMode(self, port):
    '''Sets sampling mode to 20 readings per seconds.'''
    self.Send('SENSe%d:MRATe NORMal' % port)

  def ToDoubleMode(self, port):
    '''Sets sampling mode to 40 readings per seconds.'''
    self.Send('SENSe%d:MRATe DOUBle' % port)

  def ToFastMode(self, port):
    '''Sets sampling mode to fast mode, which performance depends on sensor.'''
    self.Send('SENSe%d:MRATe FAST' % port)

  # Range related methods.
  def SetRange(self, port, range_setting=None):
    '''Selects a sensor's range (lower or upper).

    Args:
      range_setting: None to enable auto-range feature. To speed up the
        measurement, caller can specify the range manually based on the
        expected power. To manually set the range, use 0 to indicate a
        lower range and 1 for the upper range. Because range definition
        varies from sensor to sensor, check the manual before using this
        function.
    '''
    assert range_setting in [None, 0, 1]
    if range_setting is None:
      self.Send('SENSe%d:POWer:AC:RANGe:AUTO 1' % port)
    else:
      self.Send(['SENSe%d:POWer:AC:RANGe:AUTO 0' % port,
                 'SENSe%d:POWer:AC:RANGe %d' % (port, range_setting)])

  # Average related methods.
  def SetAverageFilter(self, port, avg_length):
    '''Sets the average filter.

    There are three different average filters available, averaging disable,
    auto averaging and average with a specific window length.

    Args:
      avg_length: Use None for averaging disable, -1 for auto averaging and
        other positive numbers for specific window length.
    '''
    if avg_length is None:
      # Disable the average filter.
      self.Send('SENSe%d:AVERage:STATe 0' % port)
    else:
      self.Send('SENSe%d:AVERage:STATe 1' % port)
      if avg_length > 0:
        self.Send(['SENSe%d:AVERage:COUNt:AUTO 0' % port,
                   'SENSe%d:AVERage:COUNt %d' % (port, avg_length)])
      elif avg_length == -1:
        # Use built-in auto average feature.
        self.Send('SENSe%d:AVERage:COUNt:AUTO 1' % port)
      else:
        raise ValueError('Invalid avg_length setting [%s]' % avg_length)

  # Frequency related methods.
  def SetMeasureFrequency(self, port, freq):
    self.Send(['SENSe%d:FREQuency %s' % (port, freq),
               'SENSe%d:CORRection:GAIN2:STATe 0' % port])

  # Trigger related methods.
  def SetContinuousTrigger(self, port):
    '''Sets the trigger to repeatedly active.'''
    self.Send(['INITiate%d:CONTinuous ON' % port])

  def SetOnetimeTrigger(self, port):
    '''Sets the trigger to active only once.'''
    self.Send(['INITiate%d:CONTinuous OFF' % port])

  def SetTriggerToFreeRun(self, port):
    '''Sets unconditional trigger (i.e. FreeRun mode).'''
    self.Send(['TRIGger%d:SOURce IMMediate' % port])

  def EnableTriggerImmediately(self, port):
    '''Forces to trigger immediately.'''
    self.Send(['INITiate%d:IMMediate' % port])

  def MeasureOnce(self, port):
    '''Performs a single measurement.'''
    ret = self.Query('FETCh%d?' % port, formatter=float)
    return ret

  def MeasureOnceInBinary(self, port):
    '''Performs a single measurement in binary format.'''
    def UnpackBinaryInDouble(binary_array):
      if len(binary_array) != 8:
        raise Error('Binary double must be 8 bytes'
                    ' not %d bytes.' % len(binary_array))
      return struct.unpack('>d', binary_array)[0]

    ret = self.QueryWithoutErrorChecking(
        'FETCh%d?' % port, 8, formatter=UnpackBinaryInDouble)
    return ret

  def MeasureInBinary(self, port, avg_length):
    '''Performs measurements in binary format and returns its average.'''
    assert avg_length > 0, 'avg_length need to be greater than 1'
    power = [self.MeasureOnceInBinary(port) for _ in xrange(avg_length)]
    return sum(power) / float(avg_length)
