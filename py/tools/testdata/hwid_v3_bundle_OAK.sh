#!/bin/sh
#
# Copyright 2012 The Chromium OS Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.
#
# This is a self-extraction package for ChromeOS HWID.
# Syntax: $0 [stateful_partition_device]

START_DIR="$(pwd)"
MOUNT_DIR=""
TARGET_BASE_MOUNT="dev_image/factory"
TARGET_BASE_LIVE="/usr/local/factory"
TARGET_NAME="hwid"

on_exit() {
  cd "$START_DIR"
  if [ -d "$MOUNT_DIR" ]; then
    sudo umount "$MOUNT_DIR" || true
    rmdir "$MOUNT_DIR" || true
  fi
}

die() {
  echo "ERROR: $*" 1>&2
  exit 1
}

die_usage() {
  die "Usage: $0 [stateful_partition_device_or_folder]"
}

setup_target() {
  local target_dir=""
  local recreate_folder="TRUE"

  case "$#" in
    0 )
      target_dir="$TARGET_BASE_LIVE/$TARGET_NAME"
      echo "Updating live image path $target_dir..."
      ;;
    1 )
      local state_dev="$1"
      if [ -b "$state_dev" ]; then
        echo "Updating to stateful partition $state_dev..."
        MOUNT_DIR="$(mktemp -d /tmp/hwid_XXXXXXXX)"
        sudo mount "$state_dev" "$MOUNT_DIR" || die "Failed to mount."
        target_dir="$MOUNT_DIR/$TARGET_BASE_MOUNT/$TARGET_NAME"
      elif [ -d "$state_dev" ]; then
        echo "Updating to folder $state_dev..."
        target_dir="$state_dev"
        # This is usually for manually debugging so don't remove existing files
        recreate_folder=""
      else
        die_usage
      fi
      ;;
    * )
      die_usage
      ;;
  esac

  if [ -n "$recreate_folder" ]; then
    # For a valid target, the parent folder should alread exist.
    if [ ! -d "$(dirname "$target_dir")" ]; then
      die "Invalid target ($target_dir). Missing required folders."
    fi
    # Now, update $target_dir
    sudo rm -rf "$target_dir" || die "Failed to erase $target_dir"
    sudo mkdir -p "$target_dir" || die "Failed to mkdir $target_dir"
  fi

  # Move to $target_dir for file extraction
  cd "$target_dir"
}

set -e
trap on_exit EXIT
setup_target "$@"

# force shar to overwrite files
set -- "-c"

# ----- Following data is generated by shar -----
#!/bin/sh
# This is a shell archive (produced by GNU sharutils 4.14).
# To extract the files from this archive, save it to some FILE, remove
# everything before the '#!/bin/sh' line above, then type 'sh FILE'.
#
lock_dir=_sh00617
# Made on 2017-05-05 14:02 CST by <youcheng@youcheng-z620.tpe.corp.google.com>.
# Source directory was '/tmp/tmp.nebn3TNUJl'.
#
# Existing files will *not* be overwritten, unless '-c' is specified.
#
# This shar contains:
# length mode       name
# ------ ---------- ------------------------------------------
#    870 -rw-r--r-- OAK
#
MD5SUM=${MD5SUM-md5sum}
f=`${MD5SUM} --version | egrep '^md5sum .*(core|text)utils'`
test -n "${f}" && md5check=true || md5check=false
${md5check} || \
  echo 'Note: not verifying md5sums.  Consider installing GNU coreutils.'
if test "X$1" = "X-c"
then keep_file=''
else keep_file=true
fi
echo=echo
save_IFS="${IFS}"
IFS="${IFS}:"
gettext_dir=
locale_dir=
set_echo=false

for dir in $PATH
do
  if test -f $dir/gettext \
     && ($dir/gettext --version >/dev/null 2>&1)
  then
    case `$dir/gettext --version 2>&1 | sed 1q` in
      *GNU*) gettext_dir=$dir
      set_echo=true
      break ;;
    esac
  fi
done

if ${set_echo}
then
  set_echo=false
  for dir in $PATH
  do
    if test -f $dir/shar \
       && ($dir/shar --print-text-domain-dir >/dev/null 2>&1)
    then
      locale_dir=`$dir/shar --print-text-domain-dir`
      set_echo=true
      break
    fi
  done

  if ${set_echo}
  then
    TEXTDOMAINDIR=$locale_dir
    export TEXTDOMAINDIR
    TEXTDOMAIN=sharutils
    export TEXTDOMAIN
    echo="$gettext_dir/gettext -s"
  fi
fi
IFS="$save_IFS"
if (echo "testing\c"; echo 1,2,3) | grep c >/dev/null
then if (echo -n test; echo 1,2,3) | grep n >/dev/null
     then shar_n= shar_c='
'
     else shar_n=-n shar_c= ; fi
else shar_n= shar_c='\c' ; fi
f=shar-touch.$$
st1=200112312359.59
st2=123123592001.59
st2tr=123123592001.5 # old SysV 14-char limit
st3=1231235901

if   touch -am -t ${st1} ${f} >/dev/null 2>&1 && \
     test ! -f ${st1} && test -f ${f}; then
  shar_touch='touch -am -t $1$2$3$4$5$6.$7 "$8"'

elif touch -am ${st2} ${f} >/dev/null 2>&1 && \
     test ! -f ${st2} && test ! -f ${st2tr} && test -f ${f}; then
  shar_touch='touch -am $3$4$5$6$1$2.$7 "$8"'

elif touch -am ${st3} ${f} >/dev/null 2>&1 && \
     test ! -f ${st3} && test -f ${f}; then
  shar_touch='touch -am $3$4$5$6$2 "$8"'

else
  shar_touch=:
  echo
  ${echo} 'WARNING: not restoring timestamps.  Consider getting and
installing GNU '\''touch'\'', distributed in GNU coreutils...'
  echo
fi
rm -f ${st1} ${st2} ${st2tr} ${st3} ${f}
#
if test ! -d ${lock_dir} ; then :
else ${echo} "lock directory ${lock_dir} exists"
     exit 1
fi
if mkdir ${lock_dir}
then ${echo} "x - created lock directory ${lock_dir}."
else ${echo} "x - failed to create lock directory ${lock_dir}."
     exit 1
fi
# ============= OAK ==============
if test -n "${keep_file}" && test -f 'OAK'
then
${echo} "x - SKIPPING OAK (file already exists)"

else
${echo} "x - extracting OAK (text)"
  sed 's/^X//' << 'SHAR_EOF' > 'OAK' &&
X
X
X
##### BEGIN CHECKSUM BLOCK
#
# WARNING: This checksum is generated and audited by Google. Do not
# modify it. If you modify it, devices' configurations will be
# invalid, and the devices may not be sold.
#
# 警告：此校验码由 Google 产生及审核，禁止手动修改。
# 若修改将使设备配置變為无效，并且不得销售此设备。
#
#####
checksum: e684ff75984ade16b513069ce4ec6933fcb21838
X
##### END CHECKSUM BLOCK. See the warning above. 请参考上面的警告。
X
X
board: OAK
X
encoding_patterns:
X  0: default
X
image_id:
X  0: PROTO
X
pattern:
X  - image_ids: [0]
X    encoding_scheme: base8192
X    fields:
X    - keyboard_field: 5
X
encoded_fields:
X  keyboard_field:
X    0: { keyboard: us }
X
components:
X  keyboard:
X    probeable: False
X    items:
X      us: { values: NULL }
X
rules:
- name: device_info.image_id
X  evaluate: SetImageId('PROTO')
SHAR_EOF
  (set 20 17 05 05 14 02 40 'OAK'
   eval "${shar_touch}") && \
  chmod 0644 'OAK'
if test $? -ne 0
then ${echo} "restore of OAK failed"
fi
  if ${md5check}
  then (
       ${MD5SUM} -c >/dev/null 2>&1 || ${echo} 'OAK': 'MD5 check failed'
       ) << \SHAR_EOF
d04925e59177982c91f5f8c6f6ecdd59  OAK
SHAR_EOF

else
test `LC_ALL=C wc -c < 'OAK'` -ne 870 && \
  ${echo} "restoration warning:  size of 'OAK' is not 870"
  fi
fi
if rm -fr ${lock_dir}
then ${echo} "x - removed lock directory ${lock_dir}."
else ${echo} "x - failed to remove lock directory ${lock_dir}."
     exit 1
fi
exit 0
