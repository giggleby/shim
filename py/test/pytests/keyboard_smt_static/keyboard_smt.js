// Copyright 2014 The ChromiumOS Authors
// Use of this source code is governed by a BSD-style license that can be
// found in the LICENSE file.

/**
 * Set the expected sequence.
 * @param {Array<number>} sequence
 */
const setExpectedSequence = (sequence) => {
  document.getElementById('expected-sequence').innerText = sequence.join(' ');
};

/**
 * Set the matched sequence.
 * @param {Array<number>} sequence
 */
const setMatchedSequence = (sequence) => {
  document.getElementById('matched-sequence').innerText = sequence.join(' ');
};

const exports = {
  setExpectedSequence,
  setMatchedSequence
};
for (const key of Object.keys(exports)) {
  window[key] = exports[key];
}
