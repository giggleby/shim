// Copyright 2022 The ChromiumOS Authors
// Use of this source code is governed by a BSD-style license that can be
// found in the LICENSE file.

const container = document.getElementById('qrcode-container');

const updateQRCode = (message) => {
  if (message['showQRcode']) {
    const args = message['args']
    const pos = args['pos'];
    const size = args['size'];
    const qrcode_str = args['qrcode'];
    showQRCode(pos, size, qrcode_str)
  } else {
    stopShowingQRCode()
  }
}

const showQRCode = (pos, size, qrcode_str) => {
  const appendQRCode = (x, y, size, qrcode_str) => {
    const style = `width: ${size}px; height: ${size}px;
                   top: ${y}px; left: ${x}px`;
    const img = goog.dom.createDom(
      'img', {'class': 'qrcode', 'style': style, 'src': qrcode_str});
    container.appendChild(img);
  };

  for (let i = 0; i < pos.length; ++i) {
    appendQRCode(pos[i][0], pos[i][1], size[i], qrcode_str);
  }
}

const stopShowingQRCode = () => {
  // Removes all QR codes.
  container.innerHTML = '';
}

window.updateQRCode = updateQRCode