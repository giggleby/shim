// Copyright 2018 The Chromium OS Authors. All rights reserved.
// Use of this source code is governed by a BSD-style license that can be
// found in the LICENSE file.

function StartFactoryPage() {
  chrome.runtime.sendMessage(null, 'StartFactoryPage');

  setTimeout(StartFactoryPage, 3000);  // retry in 3 seconds.
}

StartFactoryPage();
