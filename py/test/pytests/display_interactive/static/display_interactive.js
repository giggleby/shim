// Copyright 2022 The ChromiumOS Authors.
// Use of this source code is governed by a BSD-style license that can be
// found in the LICENSE file.
/**
 * API for display interactive test.
 */
window.DisplayInteractiveTest = class {
  constructor() {
    this.fullscreenElement = document.getElementById('fullscreen');
    this.displayDiv = document.getElementById('display-div');
  }
  /**
   * Toggles the fullscreen display visibility.
   */
  toggleFullscreen() {
    this.fullscreenElement.classList.toggle('hidden');
    window.test.setFullScreen(true);
  }
  /**
   * Show css pattern on display.
   */
  showPattern(pattern) {
    this.pattern = pattern;
    cros.factory.utils.removeClassesWithPrefix(this.displayDiv, '');
    this.displayDiv.style.backgroundImage = '';
    this.displayDiv.classList.remove('custom-image');
    this.displayDiv.classList.add(`${this.pattern}`);
  }
  /**
   * Show local image on display.
   */
  showImage(image) {
    this.displayDiv.style.backgroundImage = `url(./${image}.png)`;
    this.displayDiv.classList.add('custom-image');
  }
  /**
   * Fails the test.
   */
  failTest(reason) {
    window.test.fail(`${reason}`);
  }
};
