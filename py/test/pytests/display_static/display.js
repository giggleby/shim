// Copyright 2012 The ChromiumOS Authors
// Use of this source code is governed by a BSD-style license that can be
// found in the LICENSE file.

_IMAGE_PREFIX = 'image-';
_HEX_COLOR_PREFIX = 'hex-color-';
_STATUS_LABEL = {
    UNTESTED: _('Untested'),
    PASSED: _('Passed'),
    FAILED: _('Failed')};

/**
 * API for display test.
 */
window.DisplayTest = class {
  /**
   * @param {!Array<string>} items
   * @param {!Array<string>} symptoms
   */
  constructor(items, symptoms) {
    this.focusItem = 0;
    this.itemList = items;
    this.symptomList = symptoms;
    this.itemStatusList = [];
    this.itemSymptomStatusList = [];
    this.failedItemList = [];
    this.failedItemSymptomList = [];

    if (symptoms.length) {
      document.getElementById('display-caption').hidden = true;
    } else {
      document.getElementById('display-caption-symptom').hidden = true;
    }

    const table = document.getElementById('display-table');
    table.style.grid =
     `auto-flow 1fr / repeat(${this.symptomList.length + 2}, 1fr)`;
    this._createTableElement('');
    this.symptomList.forEach(symptom => this._createTableElement(symptom));
    this._createTableElement('status');
    for (const item of this.itemList) {
      this._createTableElement(item);
      this.itemSymptomStatusList.push([]);

      const itemStatus = this._createTableElement(_STATUS_LABEL.UNTESTED);
      itemStatus.classList.add('subtest-status-untested');
      for (const symptom of this.symptomList) {
        const symptomStatus =
          this._createTableElement('');
        symptomStatus.classList.add(`${item}-symptom-unobserved`);
        symptomStatus.style.backgroundColor = 'gray';
        this.itemSymptomStatusList.at(-1).push(symptomStatus);
      }
      this.itemStatusList.push(itemStatus);
      table.appendChild(itemStatus);
    }

    this.fullscreenElement = document.getElementById('display-full-screen');
    this._setDisplayDivClass();
    this._enableFocusItemButtons();
    this.fullscreen = false;
  }

  /**
   * Sets up table elements with label `elementName`.
   * @param {string} elementName
   * @private
   */
  _createTableElement(elementName) {
    const element = document.createElement('div');
    element.classList.add('center');
    element.appendChild(cros.factory.i18n.i18nLabelNode(elementName));
    document.getElementById('display-table').appendChild(element);
    return element;
  }

  /**
   * Sets up display div style.
   * @private
   */
  _setDisplayDivClass() {
    const displayDiv = document.getElementById('display-div');
    cros.factory.utils.removeClassesWithPrefix(displayDiv, 'subtest-');
    displayDiv.style.backgroundImage = null;
    displayDiv.style.backgroundColor = null;

    const item = this.itemList[this.focusItem];
    if (item.startsWith(_IMAGE_PREFIX)){
      displayDiv.style.backgroundImage = `url(./` +
        `${item.substring(_IMAGE_PREFIX.length)})`;
      displayDiv.classList.add('subtest-custom-image');
    } else if (item.startsWith(_HEX_COLOR_PREFIX)) {
      displayDiv.style.backgroundColor =
        `${item.substring(_HEX_COLOR_PREFIX.length)}`;
    } else {
      displayDiv.classList.add(`subtest-${item}`);
    }
  }

  /**
   * Enables the focus item button.
   * The button works only when the item is focus item.
   * @private
   */
  _enableFocusItemButtons() {
    const item = this.itemList[this.focusItem];
    const itemStatus = this.itemStatusList[this.focusItem];
    for (const symptomStatus of this.itemSymptomStatusList[this.focusItem]){
      symptomStatus.style.backgroundColor = '';
      symptomStatus.addEventListener('click', function OnClick() {
        if (!itemStatus.classList.contains('subtest-status-untested')) {
          return;
        }
        if (symptomStatus.classList.contains(`${item}-symptom-unobserved`)) {
          symptomStatus.innerHTML = '&#x2B55';
          symptomStatus.classList.replace(
            `${item}-symptom-unobserved`, `${item}-symptom-observed`);
        } else {
          symptomStatus.innerHTML = '';
          symptomStatus.classList.replace(
            `${item}-symptom-observed`, `${item}-symptom-unobserved`);
        }
      }.bind(this));
    }
    itemStatus.addEventListener('click', function OnClick() {
      if (itemStatus.classList.contains('subtest-status-untested')) {
        window.test.sendTestEvent('pass_subtest');
      }
    });
  }

  /**
   * Toggles the fullscreen display visibility.
   */
  toggleFullscreen() {
    this.fullscreen = !this.fullscreen;
    this.fullscreenElement.classList.toggle('hidden', !this.fullscreen);
    window.test.setFullScreen(this.fullscreen);
  }

  /**
   * Checks each symptom status for the focus item.
   * Records the failed symptoms in `this.failedItemSymptomList`.
   * Judges the subtest based all symptoms.
   */
  judgeSubTestWithSymptom() {
    const item = this.itemList[this.focusItem];
    var success = true;
    for (let j = 0; j < this.symptomList.length; j++) {
      const symptomStatus = this.itemSymptomStatusList[this.focusItem][j]
      symptomStatus.style.backgroundColor = 'gray';
      symptomStatus.style.opacity = 0.5;
      if (symptomStatus.classList.contains(`${item}-symptom-observed`)) {
        if (success) {
          this.failedItemSymptomList.push([]);
          success = false;
        }
        this.failedItemSymptomList.at(-1).push(this.symptomList[j]);
      }
    }
    this.judgeSubTest(success);
  }

  /**
   * Changes the status in test table based success or not.
   * Records the failed items in `this.failedItemList`.
   * Setups the display style for the next subtest.
   * Sends the test events if there are no more subtests.
   * @param {boolean} success
   */
  judgeSubTest(success) {
    const element = this.itemStatusList[this.focusItem];
    element.innerHTML = '';
    cros.factory.utils.removeClassesWithPrefix(element, 'subtest-status-');
    if (success) {
      element.classList.add('subtest-status-passed');
      element.appendChild(
        cros.factory.i18n.i18nLabelNode(_STATUS_LABEL.PASSED));
    } else {
      element.classList.add('subtest-status-failed');
      element.appendChild(
        cros.factory.i18n.i18nLabelNode(_STATUS_LABEL.FAILED));
      this.failedItemList.push(this.itemList[this.focusItem]);
    }
    this.focusItem++;
    if (this.focusItem < this.itemList.length) {
      this._setDisplayDivClass();
      this._enableFocusItemButtons();
    } else {
      window.test.sendTestEvent(
        'failed_lists',[this.failedItemList, this.failedItemSymptomList]);
    }
  }
};