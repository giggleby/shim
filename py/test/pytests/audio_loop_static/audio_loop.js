// Copyright 2013 The ChromiumOS Authors
// Use of this source code is governed by a BSD-style license that can be
// found in the LICENSE file.

const init = (requireDongle, testTitle) => {
  if (!requireDongle) {
    document.getElementById('require_dongle').style.display = 'none';
  }
  document.getElementById('test_title').innerHTML = testTitle;
};

const testInProgress = (successRate) => {
  window.template.innerHTML = '';
  if (successRate != null) {
    window.template.appendChild(cros.factory.i18n.i18nLabelNode(
        _('Loopback testing...\nSuccess Rate: {successRate}', {successRate})));
  } else {
    window.template.appendChild(
        cros.factory.i18n.i18nLabelNode('Loopback testing...'));
  }
};

const testFailResult = (successRate) => {
  window.template.innerHTML = '';
  window.template.appendChild(cros.factory.i18n.i18nLabelNode(
      _('Testing Result: Fail\nSuccess Rate: {successRate}', {successRate})));
};

const testPassResult = () => {
  window.template.innerHTML = '';
  window.template.appendChild(
      cros.factory.i18n.i18nLabelNode('Testing Result: Success!'));
};

const checkConformance = (input_device, output_device) => {
  window.template.innerHTML = '';
  if (input_device != null) {
    window.template.appendChild(cros.factory.i18n.i18nLabelNode(
      _('Running Conformance test....\n Input dev: {input_device}'
      , {input_device})));
  } else {
    window.template.appendChild(cros.factory.i18n.i18nLabelNode(
      _('Running Conformance test....\n Output dev: {output_device}'
      , {output_device})));
  }
};

const exports = {
  init,
  testInProgress,
  testFailResult,
  testPassResult,
  checkConformance
};
for (const key of Object.keys(exports)) {
  window[key] = exports[key];
}
