// Copyright (c) 2013 The Chromium OS Authors. All rights reserved.
// Use of this source code is governed by a BSD-style license that can be
// found in the LICENSE file.

window.onkeydown = function(event) {
  if (event.keyCode == 83) { // 's'
    test.sendTestEvent("start_run_test", {});
//    window.onkeydown = null;
  } else if (event.keyCode == 89) { // 'y'
    test.sendTestEvent("mark_result", 'pass');
  } else if (event.keyCode == 78) { // 'n'
    test.sendTestEvent("mark_result", 'fail');
  }
}

init = function(autostart, require_dongle) {
  if (!require_dongle)
    document.getElementById("require_dongle").style.display = "None";
  if (autostart) {
    document.getElementById("message").innerHTML = "";
    test.sendTestEvent("start_run_test", {});
  } else {
  }
}

createLabel = function(enMsg, zhMsg) {
  var enSpan = document.createElement("span");
  enSpan.className = "goofy-label-en";
  enSpan.innerText = enMsg;

  var zhSpan = document.createElement("span");
  zhSpan.className = "goofy-label-zh";
  zhSpan.innerText = zhMsg;

  var finalDiv = document.createElement("div");
  finalDiv.appendChild(enSpan);
  finalDiv.appendChild(zhSpan);

  return finalDiv;
}

testInProgress = function(success_rate) {
  var msgs = document.getElementById("message");
  msgs.innerHTML = "";
  if (success_rate != null) {
    msgs.appendChild(createLabel(
      "Loopback testing...\nSuccess Rate: " + success_rate,
      "音源回放测试中...\n成功率: " + success_rate));
  } else {
    msgs.appendChild(createLabel(
      "Loopback testing...\n",
      "音源回放测试中...\n"));
  }
}

testEnd = function() {
  var msgs = document.getElementById("message");
  msgs.innerHTML = "";
  msgs.appendChild(createLabel(
    "Test pass : Press 'y'\nTest fail : Press 'n'\nReplay : Press 's'",
    "测试成功 : 请按下 'y' 键\n测试失败 : 请按下 'n' 键\n重播 : 请按下 's' 键"
    ));
}

testFailResult = function(success_rate) {
  var msgs = document.getElementById("message");
  msgs.innerHTML = "";
  msgs.appendChild(createLabel(
    "Testing Result: Fail\nSuccess Rate : " + success_rate,
    "测试结果: 失败\n成功率: " + success_rate));
}

testPassResult = function(success_rate) {
  var msgs = document.getElementById("message");
  msgs.innerHTML = "";
  msgs.appendChild(createLabel(
    "Testing Result: Success!",
    "测试结果: 成功!"));
}
