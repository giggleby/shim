# Copyright 2019 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

# This Makefile provides different targets:
# - prepare: Generates the protobuf modules in the build directory.
# - _pack: Packages the required files together in preparation of deploying
#     to AppEngine.  This target is expected to be called by the deploy script.

PACKAGE_PATH_NAME = cros/factory/probe_info_service

# TODO(yhong): Centralize the protobuf version with the one in requirements.txt.
PROTOBUF_VERSION = 3.19.0

FACTORY_DIR = ../..
FACTORY_PY_PKG_DIR = $(FACTORY_DIR)/py_pkg
PACKAGE_PRIVATE_DIR = \
	$(FACTORY_DIR)/../factory-private/config/probe_info_service
BUILD_DIR := $(FACTORY_DIR)/build/probe_info_service
GEN_CODE_DIR = $(BUILD_DIR)/gen
PROTOC_LOCAL_BASE_DIR = $(BUILD_DIR)/protoc_local
PROTOC = $(PROTOC_LOCAL_BASE_DIR)/bin/protoc

# Reference:
# https://grpc.io/docs/protoc-installation/#install-pre-compiled-binaries-any-os
PROTOC_ARCHIVE_BASENAME = protoc-$(PROTOBUF_VERSION)-linux-x86_64.zip
PROTOC_ARCHIVE_DOWNLOAD_URL = https://github.com/protocolbuffers/protobuf/releases/download/v$(PROTOBUF_VERSION)/$(PROTOC_ARCHIVE_BASENAME)

PROTOC_ARCHIVE_FULLNAME = $(BUILD_DIR)/$(PROTOC_ARCHIVE_BASENAME)

PACK_DEST_DIR :=

PROTO_SRC_FILES = \
	app_engine/admin.proto \
	app_engine/probe_tools/client_payload.proto \
	app_engine/stubby.proto
PROTO_PYGEN_FILES = $(patsubst \
	%.proto,$(GEN_CODE_DIR)/$(PACKAGE_PATH_NAME)/%_pb2.py, \
	$(PROTO_SRC_FILES))
PIP_REQUIREMENT_FILE = app_engine/requirements.txt
APPENGINE_CONFIGS = $(PIP_REQUIREMENT_FILE) app_engine/app.yaml

DEP_PACKAGE_PATH_NAMES = cros/factory/utils cros/factory/probe/runtime_probe

.PHONY: prepare _pack clean

prepare: $(PROTO_PYGEN_FILES)

clean:
	rm -rf "$(BUILD_DIR)"

$(GEN_CODE_DIR)/$(PACKAGE_PATH_NAME)/%_pb2.py: %.proto $(PROTOC)
	mkdir -p "$(GEN_CODE_DIR)/$(PACKAGE_PATH_NAME)" || true
	$(PROTOC) \
		-I $(FACTORY_PY_PKG_DIR) \
		--python_out="$(GEN_CODE_DIR)" \
		"$(PACKAGE_PATH_NAME)/$<"

$(PROTOC): $(PROTOC_LOCAL_BASE_DIR)

$(PROTOC_LOCAL_BASE_DIR): $(PROTOC_ARCHIVE_FULLNAME)
	rm -rf "$@"
	mkdir -p "$@" || true
	unzip -d "$@" "$<"

$(PROTOC_ARCHIVE_FULLNAME): $(PIP_REQUIREMENT_FILE)
	grep "protobuf==$(PROTOBUF_VERSION)" "$<"
	mkdir -p "$$(dirname "$@")" || true
	curl "$(PROTOC_ARCHIVE_DOWNLOAD_URL)" -L -o "$@"

_pack: prepare
	$(if $(PACK_DEST_DIR),, \
	  $(error "You must specify the dest directory by `PACK_DEST_DIR`."))
	mkdir -p "$(PACK_DEST_DIR)/$(PACKAGE_PATH_NAME)"
	find . ! -type d ! -name "*.pyc" -exec \
	    cp --parents "{}" "$(PACK_DEST_DIR)/$(PACKAGE_PATH_NAME)" ";"
	cp -r . "$(PACK_DEST_DIR)/$(PACKAGE_PATH_NAME)"
	for path_name in $(DEP_PACKAGE_PATH_NAMES); \
	  do \
	    mkdir -p "$(PACK_DEST_DIR)/$${path_name}"; \
	    ( \
	      cd "$(FACTORY_PY_PKG_DIR)/$${path_name}"; \
	      find . ! -type d ! -name "*_*test.py" ! -name "*.pyc" -exec \
	          cp --parents "{}" "$(PACK_DEST_DIR)/$${path_name}" ";" \
	    ); \
	  done
	cp -Trf "$(PACKAGE_PRIVATE_DIR)" "$(PACK_DEST_DIR)/$(PACKAGE_PATH_NAME)"
	cp -r "$(GEN_CODE_DIR)/"* "$(PACK_DEST_DIR)"
	cp $(APPENGINE_CONFIGS) "$(PACK_DEST_DIR)"
