# Copyright 2016 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

# This Makefile provides different targets:
# - closure: Build static resources in Closure (js, css)
# - par: Archived python files, with minimal resources.
# - toolkit: Installer for factory test DUT software.
# - overlord: Overlord the remote monitoring daemon.
# - doc: HTML documentation.
# - bundle: everything for deployment, including doc, toolkit, setup, ... etc.

# Some targets, including 'par' and 'toolkit', are using a 'resource system'.
# Source files from factory repo and factory-board/files were collected
# when building the 'resource' target. Other portage packages can also put what
# should be added into toolkit and par into BOARD_RESOURCES_DIR. For example,
# files downloaded from CPFE or localmirror.
#
# Resource files should be named as TARGET-NAME.tar. For example,
# 'toolkit-webgl.tar' refers to a webgl resource only for toolkit (not par),
# 'par-shopfloor.tar' refers to a shopfloor resource only for PAR (not toolkit),
# 'resource-l10n.tar' refers to a resource that toolkit and PAR will all have.

# For debug and testing purposes, the Makefile also supports other virtual
# targets like presubmit-*, lint, test, overlay-* ... etc.

# Local environment settings
REPO_DIR := ../../..
MK_DIR := devtools/mk

include $(MK_DIR)/common.mk

BUILD_DIR ?= build
RESOURCE_DIR ?= $(BUILD_DIR)/resource
RESOURCE_PATH ?= $(RESOURCE_DIR)/factory.tar
RESOURCE_SRC_DIR ?= resources
BUNDLE_DIR ?= \
  $(if $(DESTDIR),$(DESTDIR)/$(TARGET_DIR)/bundle,$(BUILD_DIR)/bundle)
TEMP_DIR ?= $(BUILD_DIR)/tmp
TEMP_BOARD_FILES_DIR ?= $(TEMP_DIR)/board_files_dir

# Global environment settings
SHELL := bash
OUTOFTREE_BUILD ?=
PYTHON ?= python3
TARGET_DIR = /usr/local/factory

# Build and board config settings
STATIC ?= false
BOARD_RESOURCES_DIR ?= $(SYSROOT)/usr/share/factory/resources
# The resource must be extracted in ordered so we cannot use * in wildcard.
OVERLAY_RESOURCES ?= $(wildcard \
  $(BOARD_RESOURCES_DIR)/ebuild-source-baseboard-overlay.tar \
  $(BOARD_RESOURCES_DIR)/ebuild-source-board-overlay.tar)
BOARD_TARGET_DIR ?= $(SYSROOT)$(TARGET_DIR)
SYSROOT ?= $(if $(BOARD),/build/$(BOARD),/)
# The SETUP_BIN is for setup/ in factory bundle, for setting up and preparing
# images that partners usually run on an x86_64 server (same environment running
# cros_sdk or chroot). So this is / instead of SYSROOT / ROOT.
SETUP_BIN_ROOT ?= /

PAR_TEMP_DIR = $(TEMP_DIR)/par
PAR_OUTPUT_DIR = $(BUILD_DIR)/par
PAR_NAME = factory.par
SETUP_PAR_NAME = setup_tools.par
SETUP_PAR_MODULES = $(shell cat $(MK_DIR)/setup_tools_modules.lst)

TOOLKIT_VERSION ?= $(shell $(MK_DIR)/toolkit_version.sh)
TOOLKIT_FILENAME ?= install_factory_toolkit.run
TOOLKIT_TEMP_DIR = $(TEMP_DIR)/toolkit
TOOLKIT_OUTPUT_DIR = $(BUILD_DIR)

PROJECT_TEMP_DIR = $(TEMP_DIR)/project

DOC_TEMP_DIR = $(TEMP_DIR)/docsrc
DOC_ARCHIVE_PATH = $(BUILD_DIR)/doc.zip
DOC_OUTPUT_DIR = $(BUILD_DIR)/doc
DOC_PUBLISH_URL = gs://chromeos-factory-docs/sdk
DOC_MD_DIR = md

EBUILD_TEMP_DIR = $(TEMP_DIR)/ebuild
EBUILD_TEST_BLOCKED_LIST = \
  atlas \
  aurora \
  dedede \
  endeavour \
  excelsior \
  hatch \
  kukui \
  nocturne \
  soraka

PROTO_FILES = $(wildcard proto/*.proto)

HTML_SOURCE_DIR = \
  misc \
  py/goofy

HTML_SOURCE_FILES = \
  $(shell find $(HTML_SOURCE_DIR) -name '*.html')

CLOSURE_DIR = py/goofy/static
CLOSURE_OUTPUT_FILENAMES = js/goofy.js css/closure.css
CLOSURE_OUTPUT_DIR ?= \
  $(abspath $(if $(OUTOFTREE_BUILD),$(BUILD_DIR)/closure,$(CLOSURE_DIR)))

CROS_REGIONS_DATABASE ?= $(SYSROOT)/usr/share/misc/cros-regions.json
TEST_RUNNER = bin/run_unittests

# External dependency.
OVERLORD_DEPS_URL ?= \
  gs://chromeos-localmirror/distfiles/overlord-deps-0.0.3.tar.gz
OVERLORD_DEPS_DIR ?= $(BUILD_DIR)/dist/go
# This must match chromeos-base/factory/factory-9999.ebuild.
WEBGL_AQUARIUM_URI ?= \
  gs://chromeos-localmirror/distfiles/webgl-aquarium-20221212.tar.zst
WEBGL_AQUARIUM_DIR ?= $(BUILD_DIR)/dist/webgl_aquarium_static
# Following versions must match dev-libs/closure-library/*.ebuild.
CLOSURE_LIB_GITREV ?= 26b34f2241fece8df8d7424a275b0e0ce571303b
CLOSURE_LIB_URL ?= \
  gs://chromeos-localmirror/distfiles/closure-library-20211107.tar.gz
CLOSURE_LIB_DIR ?= $(BUILD_DIR)/dist/closure-library-$(CLOSURE_LIB_GITREV)
CLOSURE_COMPILER ?= $(MK_DIR)/closure-compiler-host.sh

LINT_BLOCKLIST=$(shell cat $(MK_DIR)/pylint.blocklist | grep -v '^\#')
LINT_FILES=$(shell find py go po devtools -name '*.py' -type f | sort)
LINT_ALLOWLIST=$(filter-out $(LINT_BLOCKLIST),$(wildcard $(LINT_FILES)))

MYPY_FILES=./
MYPY_CONFIG ?= $(MK_DIR)/mypy.ini

CROS_CHROOT_VERSION := $(wildcard /etc/cros_chroot_version)
ENTER_CHROOT_PREFIX := $(if $(CROS_CHROOT_VERSION)\
  ,,cros_sdk --working-dir . )

# Substitute PRESUBMIT_FILES to relative path (similar to
# GNU realpath "--relative-to=.", but works on non-GNU realpath).
PRESUBMIT_FILES := \
  $(if $(PRESUBMIT_FILES), \
    $(shell realpath $$PRESUBMIT_FILES | sed "s'^$$(realpath $$(pwd))/''g"))

PRESUBMIT_TARGETS := \
  presubmit-deps \
  presubmit-format \
  presubmit-lint \
  presubmit-lint-html \
  presubmit-shebang \
  presubmit-markdown \
  presubmit-po \
  presubmit-mypy \
  presubmit-test

# Virtual targets. The '.phony' is a special hack to allow making targets with
# wildchar (for instance, overlay-%) to be treated as .PHONY.
.PHONY: \
  .phony default clean closure proto overlord ovl-bin par doc resource toolkit \
  bundle presubmit $(PRESUBMIT_TARGETS) \
  lint smartlint smart_lint test test-critical overlay publish-docs po \
  test-list-check ebuild-unit-test ebuild-test project-toolkits

# This must be the first rule.
default: closure

clean:
	$(MAKE) -C $(CLOSURE_DIR) OUTPUT_DIR=$(CLOSURE_OUTPUT_DIR) $@
	rm -rf $(RESOURCE_DIR) $(TEMP_DIR) $(BUILD_DIR) $(BUNDLE_DIR)

# Currently the only programs using Closure is in Goofy.
closure: $(CLOSURE_LIB_DIR)
	$(MAKE) -C $(CLOSURE_DIR) OUTPUT_DIR=$(CLOSURE_OUTPUT_DIR) \
	  CLOSURE_COMPILER=$(realpath $(CLOSURE_COMPILER)) \
	  CLOSURE_LIB_DIR=$(realpath $(CLOSURE_LIB_DIR))

# Regenerates the reg code and hwid_feature_requirement proto.
# Use this build target to update pb2 file in source code.
proto:
	$(foreach file,\
	  $(PROTO_FILES),\
	  $(info - Compiling proto resource file $(file)) \
	  protoc $(file) --python_out=py${\n} )

# Resource/Toolkit uses the pb2 file generated at build time.
# The reason we're not incorporating it into `make proto`
# is that patching source code will fail due to permission issue when emerge.
define func-gen-and-add-pb2-files-to-resource
	mkdir -p $(TEMP_DIR)/py
	$(foreach file,\
	  $(PROTO_FILES),\
	  $(info - Compiling proto resource file $(file)) \
	  protoc $(file) --python_out=$(TEMP_DIR)/py${\n} )
	tar -rf $(RESOURCE_PATH) -C $(TEMP_DIR) py/proto
endef

func-extract-from-url = @\
	mkdir -p $(1) ;\
	gsutil cp $(2) $(1)/. ;\
	tar -xf $(1)/$(notdir $(2)) -C $(1) ; \
	test -d $@

$(OVERLORD_DEPS_DIR):
	$(call func-extract-from-url,$(dir $@),$(OVERLORD_DEPS_URL))

$(WEBGL_AQUARIUM_DIR):
	$(call func-extract-from-url,$(dir $@),$(WEBGL_AQUARIUM_URI))

$(CLOSURE_LIB_DIR):
	$(call func-extract-from-url,$(dir $@),$(CLOSURE_LIB_URL))

# TODO(hungte) Change overlord to build out-of-tree.
overlord: $(OVERLORD_DEPS_DIR)
	$(MAKE) -C go/src/overlord DEPS=false STATIC=$(STATIC) \
	  GOPATH=$(realpath $(OVERLORD_DEPS_DIR)):$(realpath go)
	# To install, get go/bin/{overlordd,ghost}, and go/src/overlord/app.

ovl-bin:
	# Create virtualenv environment
	rm -rf $(BUILD_DIR)/.env
	virtualenv $(BUILD_DIR)/.env
	# Build ovl binary with pyinstaller
	cd $(BUILD_DIR); \
	  source .env/bin/activate; \
	  pip install jsonrpclib ws4py pyinstaller pyyaml; \
	  pyinstaller --onefile $(CURDIR)/py/tools/ovl.py

# Checks if a package is properly installed. Append the package to
# $(TEMP_DIR)/reinstall if we need to reinstall it.
# Usage: $(call func-check-package,PACKAGE,TEST_RULE)
func-check-package = @\
  if ! $(2); then \
    echo "Need to run 'emerge-$(BOARD) $(1)' for rule '$(2)'."; \
    echo -n " $(1)" >> $(TEMP_DIR)/reinstall; \
  fi ${\n}

# Checks if all resources (from ebuild packages) are ready.
# The function check by comparing ebuild and package file timestamp, but 'git
# checkout' does not keep file timestamps, and portage looks at version instead
# of timestamp. So pre-built package may be older than ebuild files, and this
# will be a problem for fresh checkout.  The solution is to do timestamp
# comparison only in an interactive quickfix (modify, make, test) cycle, by
# checking if the build is triggered by ebuild ($(FROM_EBUILD) is set in
# factory-9999.ebuild).
define func-check-overlay-package
# Declare some useful variables.
# The $(1)_EBUILD variable should be defined in common.mk.
@$(eval CURRENT_EBUILD := $($(1)_EBUILD))
@$(eval CURRENT_PACKAGE_NAME := $(notdir $(realpath $(dir $(CURRENT_EBUILD)))))
@$(eval CURRENT_PACKAGE_FILE = \
  $(if $(CURRENT_EBUILD),$(SYSROOT)/packages/chromeos-base/$(basename \
    $(notdir $(CURRENT_EBUILD))).tbz2))
# Check if overlay resources are out of date
$(if $(CURRENT_EBUILD),\
  $(call func-check-package,$(CURRENT_PACKAGE_NAME), \
    [ "$(realpath $(CURRENT_EBUILD))" -ot "$(CURRENT_PACKAGE_FILE)" ]))
endef

# Add all available SSH identities to misc/sshkeys. These includes testing_rsa
# and partner_testing_rsa if accessible.
define func-add-ssh-identities
	@mkdir -p $(TEMP_DIR)/misc/sshkeys
	@-cp \
	  $(REPO_DIR)/chromite/ssh_keys/testing_rsa \
	  $(REPO_DIR)/chromite/ssh_keys/testing_rsa.pub \
	  $(REPO_DIR)/sshkeys/partner_testing_rsa \
	  $(REPO_DIR)/src/private-overlays/chromeos-overlay/chromeos-base/chromeos-ssh-testkeys/files/partner_testing_rsa.pub \
	  $(TEMP_DIR)/misc/sshkeys
	tar -rf $(RESOURCE_PATH) -C $(TEMP_DIR) misc/sshkeys
endef

check-overlay-dependency: .phony
	@rm -f $(TEMP_DIR)/reinstall
	@$(info Checking region database...)
	@$(call func-check-package,chromeos-regions, \
	  [ -e "$(CROS_REGIONS_DATABASE)" ] )
	@$(if $(FROM_EBUILD),,$(call func-check-overlay-package,BASEBOARD))
	@$(if $(FROM_EBUILD),,$(call func-check-overlay-package,BOARD))
	@if [ -e "$(TEMP_DIR)/reinstall" ] ; then \
	  $(MK_DIR)/die.sh \
	    "Need to run 'emerge-$(BOARD) `cat $(TEMP_DIR)/reinstall`'." ; \
	fi

# Prepare files from source folder into resource folder.
resource: closure po
	@$(info Create $(TEMP_BOARD_FILES_DIR).)
	rm -rf $(TEMP_BOARD_FILES_DIR)
	mkdir -p $(TEMP_BOARD_FILES_DIR)
	$(foreach file,\
	  $(OVERLAY_RESOURCES), \
	  $(info Target '$@' found board resource file $(file)) \
	  tar -xf $(file) -C $(TEMP_BOARD_FILES_DIR)${\n})
	@$(info Create resource $(if $(BOARD),for [$(BOARD)],without board).)
	mkdir -p $(RESOURCE_DIR)
	tar -cf $(RESOURCE_PATH) -X $(MK_DIR)/resource_exclude.lst \
	  bin misc py py_pkg sh init \
	  --exclude '$(RESOURCE_SRC_DIR)' -C $(TEMP_BOARD_FILES_DIR) .
	tar -rf $(RESOURCE_PATH) -C $(BUILD_DIR) locale
	$(call func-add-ssh-identities)
	$(call func-gen-and-add-pb2-files-to-resource)
	$(if $(OUTOFTREE_BUILD),\
	  tar -rf $(RESOURCE_PATH) --transform 's"^"./py/goofy/static/"' \
	    -C "$(CLOSURE_OUTPUT_DIR)" $(CLOSURE_OUTPUT_FILENAMES))
	$(if $(wildcard $(CROS_REGIONS_DATABASE)),\
	  tar -rf $(RESOURCE_PATH) --transform 's"^"./py/test/l10n/"' \
	  -C $(dir $(CROS_REGIONS_DATABASE)) $(notdir $(CROS_REGIONS_DATABASE)))
	$(foreach file,\
	  $(wildcard $(BOARD_RESOURCES_DIR)/$@-*.tar \
	             $(BOARD_RESOURCES_DIR)/factory-*.tar),\
	  $(info - Found board resource file $(file)) \
	  tar -Af $(RESOURCE_PATH) $(file)${\n})
	$(MK_DIR)/create_resources.py -v --output_dir $(RESOURCE_DIR) \
	  --sysroot $(SYSROOT)  --resources $(RESOURCE_SRC_DIR) \
	  --board_resources $(TEMP_BOARD_FILES_DIR)/$(RESOURCE_SRC_DIR)

# Apply files from BOARD_RESOURCES_DIR to particular folder.
# Usage: $(call func-apply-board-resources,RESOURCE_TYPE,OUTPUT_FOLDER)
func-apply-board-resources = @\
	$(foreach file,$(wildcard \
	  $(BOARD_RESOURCES_DIR)/$(1)-*.tar $(RESOURCE_DIR)/$(1)-*.tar),\
	  $(info - Found board resource file $(file) extract to $(2))${\n} \
	  tar -xf $(file) -C $(2)${\n})

# Make and test a PAR file. The PAR will be tested by importing state and run as
# gooftool.
# Usage: $(call func-make-par,OUTPUT.par,OPTIONS,INPUT_DIR)
func-make-par = @\
	@echo "Building PAR $(1)..." && \
	  mkdir -p "$(dir $(1))" && \
	  $(3)/bin/make_par $(2) -o $(1) && \
	  echo -n "Checking PAR invocation..." && \
	  PYTHONPATH=$(1) $(PYTHON) -c 'import cros.factory.test.state' && \
	  $(1) gooftool --help | grep -q '^usage: gooftool' && \
	  echo " Good."

# Builds executable python archives.
par: resource
	rm -rf $(PAR_TEMP_DIR); mkdir -p $(PAR_TEMP_DIR)
	tar -xf $(RESOURCE_PATH) -C $(PAR_TEMP_DIR)
	mkdir -p "$(PAR_OUTPUT_DIR)"
	bin/tiny_par --pkg py_pkg -o "$(PAR_OUTPUT_DIR)/$(SETUP_PAR_NAME)" \
		$(foreach module,$(SETUP_PAR_MODULES),-m $(module))
	@echo -n "Checking $(SETUP_PAR_NAME) invocation..."
	@"$(PAR_OUTPUT_DIR)/$(SETUP_PAR_NAME)" image_tool help >/dev/null 2>&1 \
		&& echo "Good"
	$(call func-apply-board-resources,par,$(PAR_TEMP_DIR))
	$(call func-make-par,$(PAR_OUTPUT_DIR)/$(PAR_NAME),,$(PAR_TEMP_DIR))
	$(call func-make-par,$(PAR_OUTPUT_DIR)/factory-mini.par,--mini,\
	  $(PAR_TEMP_DIR))

# Prepare the resources to TOOLKIT_TEMP_DIR for toolkits.
# Usage: $(call func-prepare-toolkit)
define func-prepare-toolkit
	rm -rf $(TOOLKIT_TEMP_DIR)
	mkdir -p $(TOOLKIT_TEMP_DIR)$(TARGET_DIR)
	tar -xf $(RESOURCE_PATH) -C $(TOOLKIT_TEMP_DIR)$(TARGET_DIR)
	cp -r $(WEBGL_AQUARIUM_DIR)/* \
	  $(TOOLKIT_TEMP_DIR)$(TARGET_DIR)/py/test/pytests/webgl_aquarium_static
	$(call func-apply-board-resources,toolkit,\
	  $(TOOLKIT_TEMP_DIR)$(TARGET_DIR))
	cp "$(PAR_OUTPUT_DIR)/factory.par" "$(TOOLKIT_TEMP_DIR)$(TARGET_DIR)/"
	if [ -f /usr/bin/makeself.sh ]; then \
	  cp -fL /usr/bin/makeself*.sh $(TOOLKIT_TEMP_DIR)/. ; \
	else \
	  cp -fL /usr/bin/makeself $(TOOLKIT_TEMP_DIR)/makeself.sh && \
	  cp -fL /usr/share/makeself/makeself*.sh $(TOOLKIT_TEMP_DIR)/. ; \
	fi
	# TODO(hungte) Figure out a way to get repo status in ebuild system.
	$(if $(FROM_EBUILD),,$(if $(BOARD),\
	  bin/factory_env py/toolkit/print_repo_status.py -b $(BOARD) \
	    >$(TOOLKIT_TEMP_DIR)/REPO_STATUS))
	# Install factory test enabled flag.
	touch $(TOOLKIT_TEMP_DIR)$(TARGET_DIR)/enabled
endef

# Pack the toolkit to a executable installation script.
# Usage: $(call func-pack-toolkit,target_dir,filename,version)
#   target_dir: The path of the prepared resources.
#   filename: The output path of the new factory toolkit.
#   version: String to write into TOOLKIT_VERSION.
define func-pack-toolkit
	chmod -R go=rX $(1)
	$(1)/bin/factory_env $(1)/py/toolkit/installer.py --pack-into $(2) \
	  $(if $(QUIET),--quiet) --version $(3)
endef

# Builds factory toolkit from resources.
toolkit: $(WEBGL_AQUARIUM_DIR) resource par
	rm -rf $(TOOLKIT_OUTPUT_DIR)/$(TOOLKIT_FILENAME)
	mkdir -p $(TOOLKIT_OUTPUT_DIR)
	$(call func-prepare-toolkit)
	$(call func-apply-board-resources,unibuild,$(TOOLKIT_TEMP_DIR)$(TARGET_DIR))
	$(call func-pack-toolkit,\
	  $(TOOLKIT_TEMP_DIR)$(TARGET_DIR),\
	  $(TOOLKIT_OUTPUT_DIR)/$(TOOLKIT_FILENAME),\
	  "$(BOARD) Factory Toolkit $(TOOLKIT_VERSION)")

# Build a project toolkit. func-prepare-toolkit must be called in advance.
# Usage: $(call func-build-project-toolkit,project)
#   project: The project name. Must be one of the names of the project
#     repository directories.
define func-build-project-toolkit
	rm -rf $(PROJECT_TEMP_DIR)/$(1)
	mkdir -p $(PROJECT_TEMP_DIR)/$(1)
	cp -r $(TOOLKIT_TEMP_DIR)/* $(PROJECT_TEMP_DIR)/$(1)
	$(call func-apply-board-resources,project-$(BOARD)-$(1),\
	  $(PROJECT_TEMP_DIR)/$(1)$(TARGET_DIR))
	$(call func-pack-toolkit,\
	  $(PROJECT_TEMP_DIR)/$(1)$(TARGET_DIR),\
	  $(TOOLKIT_OUTPUT_DIR)/$(1)_$(TOOLKIT_FILENAME),\
	  "$(BOARD) $(1) Factory Toolkit $(TOOLKIT_VERSION)")
endef

project-toolkits-%: .phony
	$(if $(BOARD),,$(error "You must specify a board to build project-toolkits."))
	$(call func-build-project-toolkit,$*)

# A helper target that should not be made externally.
parallel-build-project-toolkits: $(foreach file,\
	$(wildcard $(BOARD_RESOURCES_DIR)/project-$(BOARD)-*-overlay.tar),\
	project-toolkits-$(word 3,$(subst -, ,$(file))))

# Builds factory project toolkits from resources.
project-toolkits: $(WEBGL_AQUARIUM_DIR) resource par
	$(if $(BOARD),,$(error "You must specify a board to build project-toolkits."))
	rm -rf $(TOOLKIT_OUTPUT_DIR)/*_$(TOOLKIT_FILENAME)
	mkdir -p $(TOOLKIT_OUTPUT_DIR)
	$(call func-prepare-toolkit)
	$(MAKE) --output-sync=target parallel-build-project-toolkits

$(DOC_TEMP_DIR): .phony
	rm -rf $(DOC_TEMP_DIR); mkdir -p $(DOC_TEMP_DIR)
	# Do the actual build in the DOC_TEMP_DIR directory, since we need to
	# munge the docs a bit.
	rsync -a doc/ $(DOC_TEMP_DIR)
	# Generate rst sources for test cases
	CROS_FACTORY_PY_ROOT=$(realpath py_pkg) $(MK_DIR)/sphinx.sh \
	  bin/generate_rsts -o $(DOC_TEMP_DIR)
	# Copy Markdown files to temp dir
	rsync -am --files-from=<(git ls-tree -r HEAD --name-only |\
	  grep "\.\(md\|png\)$$") . \
	  $(DOC_TEMP_DIR)/$(DOC_MD_DIR)

# Creates build/doc and build/doc.zip, containing the factory SDK docs.
doc: $(DOC_TEMP_DIR)
	CROS_FACTORY_PY_ROOT=$(realpath py_pkg) $(MK_DIR)/sphinx.sh $(MAKE) -C \
	                     $(DOC_TEMP_DIR) html
	mkdir -p $(dir $(DOC_ARCHIVE_PATH))
	rm -rf $(DOC_OUTPUT_DIR)
	cp -r $(DOC_TEMP_DIR)/_build/html $(DOC_OUTPUT_DIR)
	(cd $(DOC_OUTPUT_DIR)/..; zip -qr9 - $(notdir $(DOC_OUTPUT_DIR))) \
	  >$(DOC_ARCHIVE_PATH)

linkcheck: $(DOC_TEMP_DIR)
	CROS_FACTORY_PY_ROOT=$(realpath py_pkg) $(MK_DIR)/sphinx.sh $(MAKE) -C \
	                     $(DOC_TEMP_DIR) linkcheck

# Publishes doc to https://storage.googleapis.com/chromeos-factory-docs/sdk/
publish-docs: clean
	# Force using an empty database to load whole region set from source
	CROS_REGIONS_DATABASE="/dev/null" $(MAKE) doc
	gsutil -h "Cache-Control:public, max-age=3600" -m rsync -c -d -r \
	  $(DOC_OUTPUT_DIR) $(DOC_PUBLISH_URL)

# Builds everything needed and create the proper bundle folder.
# Note there may be already few files like HWID, README, and MANIFEST.yaml
# already installed into $(SYSROOT)/usr/local/factory/bundle.
bundle: par toolkit
	$(MK_DIR)/bundle.sh \
	  "$(BUNDLE_DIR)" \
	  "$(TOOLKIT_OUTPUT_DIR)/$(TOOLKIT_FILENAME)" \
	  "$(PAR_OUTPUT_DIR)/$(SETUP_PAR_NAME)" \
	  "setup" \
	  "$(SETUP_BIN_ROOT)"
	$(call func-apply-board-resources,bundle,$(BUNDLE_DIR))
	$(info Bundle is created in $(abspath $(BUNDLE_DIR)))

lint:
	$(if $(CROS_CHROOT_VERSION),,$(info Entering chroot for "make $@" ...))
	$(ENTER_CHROOT_PREFIX)$(MK_DIR)/pylint.sh $(LINT_ALLOWLIST)

mypy:
	$(if $(CROS_CHROOT_VERSION),,$(info Entering chroot for "make $@" ...))
	$(ENTER_CHROOT_PREFIX)$(MK_DIR)/mypy.sh mypy \
		--config-file="$(MYPY_CONFIG)" $(MYPY_FILES)

format:
	$(if $(CROS_CHROOT_VERSION),,$(info Entering chroot for "make $@" ...))
	$(ENTER_CHROOT_PREFIX)$(MK_DIR)/presubmit_format.py \
	  --fix --commit=$(COMMIT) $(FILES)

# Target to lint only files that have changed.  (We allow either
# "smartlint" or "smart_lint".)
smartlint smart_lint:
	bin/smart_lint $(if $(BOARD),--overlay $(BOARD))

# Target to lint only files that have changed, including files from
# the given overlay.
smart_lint-%: .phony
	bin/smart_lint --overlay $(@:smart_lint-%=%)

presubmit-lint:
	@$(MAKE) lint LINT_FILES="$(filter %.py,$(PRESUBMIT_FILES))" 2>/dev/null

presubmit-format:
	@$(MK_DIR)/presubmit_format.py --commit=$(PRESUBMIT_COMMIT) \
		$(filter %.py,$(PRESUBMIT_FILES))

presubmit-shebang:
	@$(MK_DIR)/presubmit-shebang.py -a $(MK_DIR)/presubmit-shebang.json \
	  $(PRESUBMIT_FILES)

presubmit-deps:
	@if ! py/tools/deps.py -p $(filter py/%,$(PRESUBMIT_FILES)); then \
	  $(MK_DIR)/die.sh "Dependency check failed." \
	    "Please read py/tools/deps.conf for more information." ; \
	fi

presubmit-markdown:
	@$(MK_DIR)/presubmit_markdown.py $(PRESUBMIT_FILES)

presubmit-po:
	@$(MK_DIR)/presubmit_po.py po

presubmit-mypy:
	@$(MAKE) mypy MYPY_FILES="$(filter %.py,$(PRESUBMIT_FILES))" 2>/dev/null

presubmit-test:
	@$(MK_DIR)/$@.py $(PRESUBMIT_FILES)

presubmit:
ifeq ($(CROS_CHROOT_VERSION),)
	$(info Entering chroot for "make $@" ...)
	@$(ENTER_CHROOT_PREFIX) \
		PRESUBMIT_PROJECT="$(PRESUBMIT_PROJECT)" \
		PRESUBMIT_COMMIT="$(PRESUBMIT_COMMIT)" \
		PRESUBMIT_FILES="$(PRESUBMIT_FILES)" -- \
	  $(MAKE) -$(MAKEFLAGS) $@
else
	$(foreach target,$(PRESUBMIT_TARGETS),\
	  PYTHONDONTWRITEBYTECODE=true $(MAKE) $(target)${\n})
endif

coverage_report:
	$(if $(CROS_CHROOT_VERSION),,$(info Entering chroot for "make $@" ...))
	$(ENTER_CHROOT_PREFIX)bin/coverage_report

test:
	$(if $(CROS_CHROOT_VERSION),,$(info Entering chroot for "make $@" ...))
	$(ENTER_CHROOT_PREFIX)$(TEST_RUNNER)

test-critical:
	$(if $(CROS_CHROOT_VERSION),,$(info Entering chroot for "make $@" ...))
	$(ENTER_CHROOT_PREFIX)$(TEST_RUNNER) --no-informational --no-pass-mark

# Builds an overlay of the given board.  Use "private" to overlay
# factory-private (e.g., to build private API docs).
overlay: check-overlay-dependency
	$(if $(BOARD),,$(error "You must specify a board to build overlay."))
	rm -rf $@-$(BOARD)
	mkdir -p $@-$(BOARD)
	rsync -aK --exclude build --exclude overlay-\* ./ $@-$(BOARD)/
	$(foreach file,\
	  $(OVERLAY_RESOURCES), \
	  $(info Target '$@' found board resource file $(file)) \
	  tar -xf $(file) -C $@-$(BOARD)${\n})

overlay-%: .phony
	$(MAKE) overlay BOARD=$(subst overlay-,,$@)

# Tests the overlay of the given board.
test-overlay-%: overlay-%
	$(MAKE) -C $< test && touch .tests-passed

# Lints the overlay of the given board.
lint-overlay-%: overlay-%
	$(MAKE) -C $< lint

# Create par of the given board.
par-overlay-%: overlay-%
	$(MAKE) -C $< par

po: check-overlay-dependency
	rm -rf $(TEMP_BOARD_FILES_DIR)
	mkdir -p $(TEMP_BOARD_FILES_DIR)/po $(TEMP_BOARD_FILES_DIR)/py
	$(foreach file,\
	  $(OVERLAY_RESOURCES), \
	  $(info Target '$@' found board resource file $(file)) \
	  tar -xf $(file) -C $(TEMP_BOARD_FILES_DIR)${\n})
	$(MAKE) -C po build BOARD=$(BOARD) BUILD_DIR=$(abspath $(BUILD_DIR)) \
	  BOARD_FILES_DIR=$(TEMP_BOARD_FILES_DIR)

test-list-check:
	$(if $(TOOLKITPATH),, \
	  $(error "You must specify a TOOLKITPATH to test-list-check."))
	$(TOOLKITPATH)/bin/test_list_checker \
	  --waived W \
	  $(basename $(basename $(notdir $(wildcard \
	    $(TOOLKITPATH)/py/test/test_lists/*.test_list.json))))

ebuild-unit-test:
	$(TEST_RUNNER) --no-informational --no-pass-mark --plain-log --timeout 120

# Only run this test if factory-board is overlayed and the board name does not
# contain '-' as a substring since we want to skip *-arc and *-kernelnext
# overlays.
ebuild-test: ebuild-unit-test
ifeq ($(findstring -,$(BOARD)),)
ifneq ($(filter-out $(EBUILD_TEST_BLOCKED_LIST), $(BOARD)),)
	rm -rf $(EBUILD_TEMP_DIR)
	$(BUILD_DIR)/$(TOOLKIT_FILENAME) --noexec --noprogress --nox11 \
	  --target $(EBUILD_TEMP_DIR)
	$(MAKE) test-list-check TOOLKITPATH=$(EBUILD_TEMP_DIR)$(TARGET_DIR)
endif
endif

# Only update the file if HTML_SOURCE_FILES is changed.
$(BUILD_DIR)/.html_source_files_list: .phony
	@echo '$(HTML_SOURCE_FILES)' | cmp -s - $@ || echo '$(HTML_SOURCE_FILES)' > $@

# If we don't depend on .html_source_files_list, makefile won't re-run the
# check when a file in HTML_SOURCE_FILES is removed.
$(BUILD_DIR)/.lint-html-passed: $(BUILD_DIR)/.html_source_files_list
$(BUILD_DIR)/.lint-html-passed: $(HTML_SOURCE_FILES)
	$(info Re-run presubmit_html ...)
	@$(MK_DIR)/presubmit_html.py $(HTML_SOURCE_FILES) > $@

presubmit-lint-html: $(BUILD_DIR)/.lint-html-passed
	$(if $(shell head $<),\
	  cat $< && $(MK_DIR)/die.sh "lint-html",\
	  $(info $@ passes.))
