# Copyright 2016 The Chromium OS Authors. All rights reserved.
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
# Source files from factory repo and chromeos-factory-board/files were collected
# when building the 'resource' target. Other portage packages can also put what
# should be added into toolkit and par into BOARD_RESOURCES_DIR
# (/build/$BOARD/var/lib/factory/resources) - for example files downloaded from
# CPFE or localmirror.
#
# Resource files should be named as TARGET-NAME.tar. For example,
# 'toolkit-webgl.tar' refers to a webgl resource only for toolkit (not par),
# 'par-shopfloor.tar' refers to a shopfloor resource only for PAR (not toolkit),
# 'resource-l10n.tar' refers to a resource that toolkit and PAR will all have.

# For debug and testing purposes, the Makefile also supports other virtual
# targets like presubmit-*, lint, test, overlay-* ... etc.

# Local environment settings
MK_DIR := devtools/mk
BUILD_DIR ?= build
RESOURCE_DIR ?= $(BUILD_DIR)/resource
RESOURCE_PATH ?= $(RESOURCE_DIR)/factory.tar
BUNDLE_DIR ?= \
  $(if $(DESTDIR),$(DESTDIR)/$(TARGET_DIR)/bundle,$(BUILD_DIR)/bundle)
BOARD_BUNDLE_RESOURCE_PATH ?= $(RESOURCE_DIR)/bundle-board.tar
TEMP_DIR ?= $(BUILD_DIR)/tmp

# Global environment settings
SHELL := bash
OUTOFTREE_BUILD ?=
PYTHON ?= python
TARGET_DIR = /usr/local/factory

# Build and board config settings
STATIC ?= false
BOARD ?=
BOARD_PACKAGE_NAME ?= chromeos-factory-board
BOARD_EBUILD ?= \
  $(if $(BOARD),$(shell equery-$(BOARD) which $(BOARD_PACKAGE_NAME)))
BOARD_PACKAGE_FILE ?= \
  $(if $(BOARD_EBUILD),$(SYSROOT)/packages/chromeos-base/$(basename $(notdir \
    $(BOARD_EBUILD))).tbz2)
BOARD_FILES_DIR ?= $(if $(BOARD_EBUILD),$(dir $(BOARD_EBUILD))/files)
BOARD_RESOURCES_DIR ?= $(SYSROOT)/var/lib/factory/resources
BOARD_TARGET_DIR ?= $(SYSROOT)$(TARGET_DIR)
SYSROOT ?= $(if $(BOARD),/build/$(BOARD),/)

# Legacy board packge will install bundle files directly and will conflict with
# the new build system when we're running as out-of-tree build.
# TODO(hungte) Remove legacy board support when the migration of new build
# system is completed.
LEGACY_BOARD_IN_OUTOFTREE ?= \
  $(if $(OUTOFTREE_BUILD),$(if \
      $(filter $(BOARD_PACKAGE_NAME),chromeos-factory-board),1))

# Typically we should not make any difference between build_packages and
# "emerge-$BOARD chromeos-factory". However, to improve development experience,
# we do want to add some additional checks (that portage should solve for us)
# for developers who manually invoked 'make' or 'emerge-$BOARD'.
# The IS_BUILD_PACKAGES macro is using some undocumented environment variables
# that build_packages has set, and should only be used by "developer-friendly
# additional checks".
IS_BUILD_PACKAGES = $(if $(CHROMEOS_VERSION_STRING),True)

PAR_TEMP_DIR = $(TEMP_DIR)/par
PAR_OUTPUT_DIR = $(BUILD_DIR)/par
PAR_NAME = factory.par

TOOLKIT_VERSION ?= $(shell $(MK_DIR)/toolkit_version.sh)
TOOLKIT_FILENAME ?= install_factory_toolkit.run
TOOLKIT_TEMP_DIR = $(TEMP_DIR)/toolkit
TOOLKIT_OUTPUT_DIR = $(BUILD_DIR)

DOC_TEMP_DIR = $(TEMP_DIR)/docsrc
DOC_ARCHIVE_PATH = $(BUILD_DIR)/doc.zip
DOC_OUTPUT_DIR = $(BUILD_DIR)/doc

CLOSURE_DIR = py/goofy/static
CLOSURE_OUTPUT_FILENAMES = js/goofy.js css/closure.css
CLOSURE_OUTPUT_DIR ?= \
  $(abspath $(if $(OUTOFTREE_BUILD),$(BUILD_DIR)/closure,$(CLOSURE_DIR)))

CROS_REGIONS_DATABASE ?= $(SYSROOT)/usr/share/misc/cros-regions.json

# Battery cutoff scripts from memento_softwareupdate.
# TODO(hungte) Move these scripts to factory repo.
CUTOFF_SCRIPT_NAMES ?= \
  battery_cutoff display_wipe_message generate_finalize_request inform_shopfloor

# External dependency.
OVERLORD_DEPS_URL ?= \
  gs://chromeos-localmirror/distfiles/overlord-deps-0.0.3.tar.gz
OVERLORD_DEPS_DIR ?= $(BUILD_DIR)/dist/go
WEBGL_AQUARIUM_URI ?= \
  gs://chromeos-localmirror/distfiles/webgl-aquarium-20130524.tar.bz2
WEBGL_AQUARIUM_DIR ?= $(BUILD_DIR)/dist/webgl_aquarium_static

LINT_BLACKLIST=$(shell cat $(MK_DIR)/pylint.blacklist)
LINT_FILES=$(shell find py go -name '*.py' -type f | sort)
LINT_WHITELIST=$(filter-out $(LINT_BLACKLIST),$(LINT_FILES))

UNITTESTS=$(shell find py go -name '*_unittest.py' | sort)
UNITTESTS_BLACKLIST=$(shell cat $(MK_DIR)/unittests.blacklist)
UNITTESTS_WHITELIST=$(filter-out $(UNITTESTS_BLACKLIST),$(UNITTESTS))
TEST_EXTRA_FLAGS=

# Special variable (two blank lines) so we can invoke commands with $(foreach).
define \n


endef

# Substitute PRESUBMIT_FILES to relative path (similar to
# GNU realpath "--relative-to=.", but works on non-GNU realpath).
PRESUBMIT_FILES := \
  $(if $(PRESUBMIT_FILES), \
    $(shell realpath $$PRESUBMIT_FILES | sed "s'^$$(realpath $$(pwd))/''g"))

PRESUBMIT_TARGETS := \
  presubmit-deps presubmit-lint presubmit-test presubmit-make-factory-package

# Virtual targets. The '.phony' is a special hack to allow making targets with
# wildchar (for instance, overlay-%) to be treated as .PHONY.
.PHONY: \
  .phony default clean closure proto overlord ovl-bin par doc resource toolkit \
  bundle presubmit presubmit-chroot $(PRESUBMIT_TARGETS) \
  lint smartlint smart_lint test testall overlay check-board-resources

# This must be the first rule.
default: closure

clean:
	$(MAKE) -C $(CLOSURE_DIR) OUTPUT_DIR=$(CLOSURE_OUTPUT_DIR) $@
	rm -rf $(RESOURCE_DIR) $(TEMP_DIR) $(BUILD_DIR) $(BUNDLE_DIR)

# Currently the only programs using Closure is in Goofy.
closure:
	$(MAKE) -C $(CLOSURE_DIR) OUTPUT_DIR=$(CLOSURE_OUTPUT_DIR)

# Regenerates the reg code proto.
# TODO(jsalz): Integrate this as a "real" part of the build, rather than
# relying on regenerating it only if/when it changes. This is OK for now since
# this proto should change infrequently or never.
proto:
	protoc proto/reg_code.proto --python_out=py

func-extract-from-url = @\
	mkdir -p $(1) ;\
	gsutil cp $(2) $(1)/. ;\
	tar -xf $(1)/$(notdir $(2)) -C $(1)

$(OVERLORD_DEPS_DIR):
	$(call func-extract-from-url,$(dir $@),$(OVERLORD_DEPS_URL))

$(WEBGL_AQUARIUM_DIR):
	$(call func-extract-from-url,$(dir $@),$(WEBGL_AQUARIUM_URI))

# TODO(hungte) Change overlord to build out-of-tree.
overlord: $(OVERLORD_DEPS_DIR)
	$(MAKE) -C go/src/overlord DEPS=false STATIC=$(STATIC) \
	  GOPATH=$(realpath $(OVERLORD_DEPS_DIR)):$(realpath go)
	# To install, get go/bin/{overlord,ghost}, and go/src/overlord/app.

ovl-bin:
	# Create virtualenv environment
	rm -rf $(BUILD_DIR)/.env
	virtualenv $(BUILD_DIR)/.env
	# Build ovl binary with pyinstaller
	cd $(BUILD_DIR); \
	  source $(BUILD_DIR)/.env/bin/activate; \
	  pip install jsonrpclib ws4py pyinstaller; \
	  pyinstaller --onefile $(CURDIR)/py/tools/ovl.py

# Checks if a package is properly installed.
# Usage: $(call func-check-package,PACKAGE,TEST_RULE)
func-check-package = @\
  if ! $(2); then \
    $(MK_DIR)/die.sh "Need to run 'emerge-$(BOARD) $(1)' for rule '$(2)'." ; \
  fi ${\n}

# Checks if all board resources (from packages) are ready.
# $(BOARD_PACKAGE_NAME) is checked by comparing ebuild and package file
# timestamp, but 'git checkout' does not keep file timestamps, and portage looks
# at version instead of timestamp. So pre-built package may be older than ebuild
# files, and this will be a problem for fresh checkout.
# The solution is to ignore timestamp comparison when portage should have solved
# all dependency (i.e., build_packages).
check-board-resources:
	$(if $(BOARD_EBUILD),\
	   $(if $(IS_BUILD_PACKAGES),\
	     $(info Ignore $(BOARD_PACKAGE_NAME) check in build_packages), \
	     $(call func-check-package,$(BOARD_PACKAGE_NAME), \
	       [ "$(realpath $(BOARD_EBUILD))" -ot "$(BOARD_PACKAGE_FILE)" ])) \
	   $(call func-check-package,chromeos-regions, \
	     [ -e "$(CROS_REGIONS_DATABASE)" ] ) \
	   $(foreach name,$(CUTOFF_SCRIPT_NAMES),\
	     $(call func-check-package,memento_softwareupdate, \
	       [ -e "$(BOARD_TARGET_DIR)/sh/$(name).sh" ])))

# Prepare files from source folder into resource folder.
resource: closure check-board-resources
	@$(info Create resource $(if $(BOARD),for [$(BOARD)],without board).)
	mkdir -p $(RESOURCE_DIR)
	tar -cf $(RESOURCE_PATH) -X $(MK_DIR)/resource_exclude.lst \
	  bin misc py py_pkg sh init \
	  $(if $(wildcard $(BOARD_FILES_DIR)),-C $(BOARD_FILES_DIR) .)
	$(if $(LEGACY_BOARD_IN_OUTOFTREE),,\
	  $(if $(wildcard $(BOARD_FILES_DIR)/bundle), tar \
	    -cf $(BOARD_BUNDLE_RESOURCE_PATH) -C $(BOARD_FILES_DIR)/bundle .))
	$(if $(OUTOFTREE_BUILD),\
	  tar -rf $(RESOURCE_PATH) --transform 's"^"./py/goofy/static/"' \
	    -C "$(CLOSURE_OUTPUT_DIR)" $(CLOSURE_OUTPUT_FILENAMES))
	$(if $(wildcard $(CROS_REGIONS_DATABASE)),\
	  tar -rf $(RESOURCE_PATH) --transform 's"^"./py/test/l10n/"' \
	  -C $(dir $(CROS_REGIONS_DATABASE)) $(notdir $(CROS_REGIONS_DATABASE)))
	$(foreach name,$(CUTOFF_SCRIPT_NAMES),\
	  $(if $(wildcard $(BOARD_TARGET_DIR)/sh/$(name).sh),\
	    tar -rf $(RESOURCE_PATH) -C $(BOARD_TARGET_DIR) sh/$(name).sh${\n}))
	$(foreach file,\
	  $(wildcard $(BOARD_RESOURCES_DIR)/$@-*.tar \
	             $(BOARD_RESOURCES_DIR)/factory-*.tar),\
	  $(info - Found board resource file $(file)) \
	  tar -Af $(RESOURCE_PATH) $(file)${\n})

# Apply files from BOARD_RESOURCES_DIR to particular folder.
# Usage: $(call func-apply-board-resources,RESOURCE_TYPE,OUTPUT_FOLDER)
func-apply-board-resources = @\
	$(foreach file,$(wildcard \
	  $(BOARD_RESOURCES_DIR)/$(1)-*.tar $(RESOURCE_DIR)/$(1)-*.tar),\
	  $(info - Found board resource file $(file))${\n} \
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
	$(call func-apply-board-resources,par,$(PAR_TEMP_DIR))
	$(call func-make-par,$(PAR_OUTPUT_DIR)/$(PAR_NAME),,$(PAR_TEMP_DIR))
	$(call func-make-par,$(PAR_OUTPUT_DIR)/factory-mini.par,--mini,\
	  $(PAR_TEMP_DIR))

# Builds factory toolkit from resources.
toolkit: $(WEBGL_AQUARIUM_DIR) resource par
	rm -rf $(TOOLKIT_TEMP_DIR) $(TOOLKIT_OUTPUT_DIR)/$(TOOLKIT_FILENAME)
	mkdir -p $(TOOLKIT_TEMP_DIR)$(TARGET_DIR) $(TOOLKIT_OUTPUT_DIR)
	tar -xf $(RESOURCE_PATH) -C $(TOOLKIT_TEMP_DIR)$(TARGET_DIR)
	cp -r $(WEBGL_AQUARIUM_DIR)/* \
	  $(TOOLKIT_TEMP_DIR)$(TARGET_DIR)/py/test/pytests/webgl_aquarium_static
	$(call func-apply-board-resources,toolkit,\
	  $(TOOLKIT_TEMP_DIR)$(TARGET_DIR))
	cp "$(PAR_OUTPUT_DIR)/factory.par" "$(TOOLKIT_TEMP_DIR)$(TARGET_DIR)/"
	cp -L /usr/bin/makeself*.sh $(TOOLKIT_TEMP_DIR)/.
	# TODO(hungte) Figure out a way to get repo status in OUTOFTREE_BUILD.
	$(if $(OUTOFTREE_BUILD),,$(if $(BOARD),\
	  py/toolkit/print_repo_status.py -b $(BOARD) \
	    >$(TOOLKIT_TEMP_DIR)/REPO_STATUS))
	echo "$(BOARD) Factory Toolkit $(TOOLKIT_VERSION)" \
	  >$(TOOLKIT_TEMP_DIR)$(TARGET_DIR)/TOOLKIT_VERSION
	ln -s .$(TARGET_DIR)/TOOLKIT_VERSION $(TOOLKIT_TEMP_DIR)/VERSION
	# Install factory test enabled flag.
	touch $(TOOLKIT_TEMP_DIR)$(TARGET_DIR)/enabled
	chmod -R go=rX $(TOOLKIT_TEMP_DIR)$(TARGET_DIR)
	$(TOOLKIT_TEMP_DIR)$(TARGET_DIR)/py/toolkit/installer.py \
	  --pack-into $(TOOLKIT_OUTPUT_DIR)/$(TOOLKIT_FILENAME)

# Creates build/doc and build/doc.zip, containing the factory SDK docs.
doc:
	rm -rf $(DOC_TEMP_DIR); mkdir -p $(DOC_TEMP_DIR)
	# Do the actual build in the DOC_TEMP_DIR directory, since we need to
	# munge the docs a bit.
	rsync -a doc/ $(DOC_TEMP_DIR)
	# Generate rst sources for test cases
	bin/generate_rsts -o $(DOC_TEMP_DIR)
	CROS_FACTORY_PY_ROOT=$(realpath py_pkg) $(MAKE) -C $(DOC_TEMP_DIR) html
	mkdir -p $(dir $(DOC_ARCHIVE_PATH))
	rm -rf $(DOC_OUTPUT_DIR)
	cp -r $(DOC_TEMP_DIR)/_build/html $(DOC_OUTPUT_DIR)
	(cd $(DOC_OUTPUT_DIR)/..; zip -qr9 - $(notdir $(DOC_OUTPUT_DIR))) \
	  >$(DOC_ARCHIVE_PATH)

# Builds everything needed and create the proper bundle folder.
# Note there may be already few files like HWID, README, and MANIFEST.yaml
# already installed into $(SYSROOT)/usr/local/factory/bundle.
bundle: par doc toolkit
	$(MK_DIR)/bundle.sh \
	  "$(BUNDLE_DIR)" \
	  "$(TOOLKIT_OUTPUT_DIR)/$(TOOLKIT_FILENAME)" \
	  "$(PAR_OUTPUT_DIR)/$(PAR_NAME)" \
	  "$(DOC_ARCHIVE_PATH)" \
	  "setup" \
	  "$(SYSROOT)"
	$(call func-apply-board-resources,bundle,$(BUNDLE_DIR))
	$(info Bundle is created in $(abspath $(BUNDLE_DIR)))

lint:
	$(MK_DIR)/pylint.sh $(LINT_WHITELIST)

# Target to lint only files that have changed.  (We allow either
# "smartlint" or "smart_lint".)
smartlint smart_lint:
	bin/smart_lint $(if $(BOARD),--overlay $(BOARD))

# Target to lint only files that have changed, including files from
# the given overlay.
smart_lint-%: .phony
	bin/smart_lint --overlay $(@:smart_lint-%=%)

presubmit-chroot:
	$(foreach target,$(PRESUBMIT_TARGETS),$(MAKE) -s $(target)${\n})

presubmit-lint:
	@$(MAKE) lint LINT_FILES="$(filter %.py,$(PRESUBMIT_FILES))" 2>/dev/null

presubmit-deps:
	@if ! py/tools/deps.py $(PRESUBMIT_FILES); then \
	  $(MK_DIR)/die.sh "Dependency check failed." \
	    "Please read py/tools/deps.conf for more information." ; \
	fi

# Check that test_make_factory_package.py has been run, if
# make_factory_package.sh has changed.
presubmit-make-factory-package:
ifneq ($(filter setup/make_factory_package.sh,$(PRESUBMIT_FILES)),)
	@if [ ! setup/make_factory_package.sh -ot \
	      py/tools/.test_make_factory_package.passed ]; then \
	  $(MK_DIR)/die.sh "setup/make_factory_package.sh has changed." \
	    "Please run py/tools/test_make_factory_package.py" \
	    "(use --help for more information on how to use it if" \
	    "you do not have access to release repositories)." ; \
	fi
endif

presubmit-test:
	@$(MK_DIR)/$@.sh $(PRESUBMIT_FILES)

presubmit:
ifeq ($(wildcard /etc/debian_chroot),)
	$(info Running presubmit checks inside chroot...)
	@cros_sdk PRESUBMIT_FILES="$(PRESUBMIT_FILES)" -- \
	  $(MAKE) -C ../platform/factory -s $@-chroot
else
	@$(MAKE) -s $@-chroot
endif

test:
	@TEST_EXTRA_FLAGS=$(TEST_EXTRA_FLAGS) \
	  $(MK_DIR)/test.sh $(UNITTESTS_WHITELIST)

testall:
	@$(MAKE) --no-print-directory test TEST_EXTRA_FLAGS=--nofilter

# Builds an overlay of the given board.  Use "private" to overlay
# factory-private (e.g., to build private API docs).
overlay:
	rm -rf $@-$(BOARD)
	mkdir -p $@-$(BOARD)
	rsync -aK --exclude build --exclude overlay-\* ./ $@-$(BOARD)/
	rsync -aK $(if $(filter $(BOARD),private), \
			--exclude Makefile ../factory-private/ $@-$(BOARD)/, \
			"$(BOARD_FILES_DIR)/" $@-$(BOARD)/)

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
