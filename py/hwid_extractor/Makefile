# Copyright 2021 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

DESTDIR ?=
FACTORY_SRC_PATH ?= ..
CHROMITE_PATH ?= ../../../../../chromite
BIN_DIR ?= /usr/bin
LIB_DIR ?= /usr/local
DEST_LIB_PATH := $(DESTDIR)$(LIB_DIR)/hwid_extractor
DEST_BIN_PATH := $(DESTDIR)$(BIN_DIR)
BIN_TO_LIB_REL_PATH = \
	$(shell realpath --relative-to $(DEST_BIN_PATH) $(DEST_LIB_PATH))


CLI_SOURCES := \
	factory_env.py \
	hwid_extractor.py

UTILS_SOURCES := \
	__init__.py \
	file_utils.py \
	json_utils.py \
	platform_utils.py \
	process_utils.py \
	schema.py \
	type_utils.py

JS_SOURCES := \
	www/index.js \
	www/extension.js

HWID_EXTRACTOR_SOURCES := \
	www/index.html \
	ap_config.json \
	$(JS_SOURCES) \
	$(wildcard *.py)

SOURCES := \
	$(addprefix cli/,$(CLI_SOURCES)) \
	$(addprefix hwid_extractor/,$(HWID_EXTRACTOR_SOURCES)) \
	$(addprefix utils/,$(UTILS_SOURCES))


INSTALL_TARGET := $(addprefix install_,$(SOURCES))

.PHONY: all check_js $(INSTALL_TARGET) install

all: ap_config.json

check_js:
	closure-compiler \
	  --warning_level=VERBOSE \
	  --jscomp_warning=lintChecks \
	  --language_in ECMASCRIPT_NEXT \
	  --checks-only \
	  $(JS_SOURCES)

ap_config.json:
	$(CHROMITE_PATH)/bin/cros ap dump-config -o ap_config.json

$(INSTALL_TARGET): ap_config.json
	mkdir -p $(DEST_LIB_PATH)/py/$(dir $(@:install_%=%))
	cp -P $(FACTORY_SRC_PATH)/$(@:install_%=%) \
		$(DEST_LIB_PATH)/py/$(@:install_%=%)

install: $(INSTALL_TARGET)
	# Setup py_pkg/cros
	mkdir -p $(DEST_LIB_PATH)/py_pkg/cros
	touch $(DEST_LIB_PATH)/py_pkg/cros/__init__.py

	# Setup py_pkg/cros/factory
	ln -sf ../../py $(DEST_LIB_PATH)/py_pkg/cros/factory
	mkdir -p $(DEST_BIN_PATH)

	# Setup hwid_extractor execuable
	ln -sf $(BIN_TO_LIB_REL_PATH)/py/cli/factory_env.py \
		$(DEST_BIN_PATH)/hwid_extractor
