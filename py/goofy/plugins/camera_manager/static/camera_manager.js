// Copyright 2022 The ChromiumOS Authors
// Use of this source code is governed by a BSD-style license that can be
// found in the LICENSE file.

/**
 * A map from test path to the tree node for each test.
 * @type {!Object<string, HTMLElement>}
 */
const testVideoElems = {
  user: document.getElementById('video-user'),
  environment: document.getElementById('video-environment')
};

const getMediaStream = async (facingMode, getUserMediaRetries) => {
  var i;
  for (i = 0; i < getUserMediaRetries + 1; ++i) {
    try {
      return await navigator.mediaDevices.getUserMedia({
        audio: false,
        video: {
          facingMode: { exact: facingMode }
        }
      });
    } catch (error) {
      if (error.name != "NotReadableError") {
        throw error;
      }
    }
    await cros.factory.utils.delay(1000);
  }
  throw Error('NotReadableError: Fail all retries.');
}

/**
 * Update camera state.
 *
 * @param {str} facingMode This must be one of ('user', 'environment').
 * @param {boolean} enable If true, enable the camera. Otherwise, disable it.
 * @param {boolean} hidden If true, the video is hidden.
 */
const updateCamera = async (facingMode, enable, hidden) => {
  const testVideoElem = testVideoElems[facingMode];
  testVideoElem.hidden = hidden
  const currentMediaStream = testVideoElem.srcObject;
  if(currentMediaStream !== null){
    if(enable === false) {
      currentMediaStream.getVideoTracks().forEach(track => track.stop());
      testVideoElem.srcObject = null;
    }
  } else {
    if(enable === true) {
      const mediaStream = await getMediaStream(facingMode, 5);
      testVideoElem.autoplay = true;
      testVideoElem.srcObject = mediaStream;
    }
  }
};

window.updateCamera = updateCamera;
