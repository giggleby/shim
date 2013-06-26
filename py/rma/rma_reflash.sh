#!/bin/bash
#
# Copyright (c) 2013 The Chromium OS Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

SCRIPT_DIR="$(dirname "$(readlink "$0")")"

DUT_CONTROL_CMD="/usr/local/bin/python /usr/local/bin/dut-control-2.6"
EC_FIRMWARE_BINARY="${SCRIPT_DIR}/firmware/ec.bin"
FLASHROM_CMD="${SCRIPT_DIR}/flashrom"
OPENOCD_CMD="${SCRIPT_DIR}/openocd/openocd"
OPENOCD_CONFIG_DIR="${SCRIPT_DIR}/openocd"
OUTPUT_DIR="${SCRIPT_DIR}/shopfloor_data"
RMA_CREATE_CSV_CMD="${SCRIPT_DIR}/rma_save_data.py"

function show_ok() {
  printf "\033[1;32m"
  echo "      OOOOOOOOO      KKKKKKKKK    KKKKKKK "
  echo "    OO:::::::::OO    K:::::::K    K:::::K "
  echo "  OO:::::::::::::OO  K:::::::K    K:::::K "
  echo " O:::::::OOO:::::::O K:::::::K   K::::::K "
  echo " O::::::O   O::::::O KK::::::K  K:::::KKK "
  echo " O:::::O     O:::::O   K:::::K K:::::K    "
  echo " O:::::O     O:::::O   K::::::K:::::K     "
  echo " O:::::O     O:::::O   K:::::::::::K      "
  echo " O:::::O     O:::::O   K:::::::::::K      "
  echo " O:::::O     O:::::O   K::::::K:::::K     "
  echo " O:::::O     O:::::O   K:::::K K:::::K    "
  echo " O::::::O   O::::::O KK::::::K  K:::::KKK "
  echo " O:::::::OOO:::::::O K:::::::K   K::::::K "
  echo "  OO:::::::::::::OO  K:::::::K    K:::::K "
  echo "    OO:::::::::OO    K:::::::K    K:::::K "
  echo "      OOOOOOOOO      KKKKKKKKK    KKKKKKK "
  echo
  printf "\033[0m"
}

function show_fail() {
  printf "\033[1;31m"
  echo " FFFFFFFFFFFFFFFFFFFFFF         AAA                IIIIIIIIII LLLLLLLLLLL               !!! "
  echo " F::::::::::::::::::::F        A:::A               I::::::::I L:::::::::L              !!:!!"
  echo " F::::::::::::::::::::F       A:::::A              I::::::::I L:::::::::L              !:::!"
  echo " FF::::::FFFFFFFFF::::F      A:::::::A             II::::::II LL:::::::LL              !:::!"
  echo "   F:::::F       FFFFFF     A:::::::::A              I::::I     L:::::L                !:::!"
  echo "   F:::::F                 A:::::A:::::A             I::::I     L:::::L                !:::!"
  echo "   F::::::FFFFFFFFFF      A:::::A A:::::A            I::::I     L:::::L                !:::!"
  echo "   F:::::::::::::::F     A:::::A   A:::::A           I::::I     L:::::L                !:::!"
  echo "   F:::::::::::::::F    A:::::A     A:::::A          I::::I     L:::::L                !:::!"
  echo "   F::::::FFFFFFFFFF   A:::::AAAAAAAAA:::::A         I::::I     L:::::L                !:::!"
  echo "   F:::::F            A:::::::::::::::::::::A        I::::I     L:::::L                !!:!!"
  echo "   F:::::F           A:::::AAAAAAAAAAAAA:::::A       I::::I     L:::::L         LLLLLL  !!! "
  echo " FF:::::::FF        A:::::A             A:::::A    II::::::II LL:::::::LLLLLLLLL:::::L      "
  echo " F::::::::FF       A:::::A               A:::::A   I::::::::I L::::::::::::::::::::::L  !!! "
  echo " F::::::::FF      A:::::A                 A:::::A  I::::::::I L::::::::::::::::::::::L !!:!!"
  echo " FFFFFFFFFFF     AAAAAAA                   AAAAAAA IIIIIIIIII LLLLLLLLLLLLLLLLLLLLLLLL  !!! "
  echo
  printf "\033[0m"
}

function cleanup() {
  rm -rf "${TMPDIR}"
}

trap cleanup EXIT

function fail() {
  local message="$@"
  show_fail
  if [ -n "${message}" ]; then
    echo "${message}"
  fi
  continue
}

function flash_ec() {
  #Reset the EC
  ${DUT_CONTROL_CMD} cold_reset:on
  ${DUT_CONTROL_CMD} cold_reset:off

  #Flash new EC firmware
  OCD_CFG="servo_v2_slower.cfg"
  OCD_CMDS="init;"
  OCD_CMDS="${OCD_CMDS} flash_lm4 ${EC_FIRMWARE_BINARY} 0;"
  OCD_CMDS="${OCD_CMDS} unprotect_link;"
  OCD_CMDS="${OCD_CMDS} shutdown;"

  ${DUT_CONTROL_CMD} jtag_buf_on_flex_en:on
  ${DUT_CONTROL_CMD} jtag_buf_en:on

  timeout 30 ${OPENOCD_CMD} -s "${OPENOCD_CONFIG_DIR}" -f "${OCD_CFG}" \
      -c "${OCD_CMDS}"
  return $?
}

function write_protect_is_disabled() {
  ${DUT_CONTROL_CMD} fw_wp | grep -q "fw_wp:off"
  return $?
}

function servod_is_running() {
  pgrep -f servod-2.6 1>/dev/null
  return $?
}

function servo_is_connected() {
  ${DUT_CONTROL_CMD} blinky 2>/dev/null 1>/dev/null
  return $?
}

function dut_is_alive() {
  ${DUT_CONTROL_CMD} spi2_vref:pp3300 spi2_buf_en:on spi2_buf_on_flex_en:on \
                     spi_hold:off cold_reset:on
  ${FLASHROM_CMD} -p ft2232_spi:type=servo-v2 --flash-name | \
      grep -qv "unknown SPI chip"
  local result=$?
  ${DUT_CONTROL_CMD} spi2_vref:off spi2_buf_en:off spi2_buf_on_flex_en:off
  return ${result}
}

function save_volitile_data() {
  local rma_number="$1"
  TMPDIR="$(mktemp -d --tmpdir tmp.reflash.XXXXXXX)"
  RO_VPD="${TMPDIR}/ro_vpd.bin"
  RW_VPD="${TMPDIR}/rw_vpd.bin"
  GBB="${TMPDIR}/gbb.bin"

  #Extract VPD and HWID information from original firmware
  ${DUT_CONTROL_CMD} spi2_vref:pp3300 spi2_buf_en:on spi2_buf_on_flex_en:on \
                     spi_hold:off cold_reset:on
  ${FLASHROM_CMD} -p ft2232_spi:type=servo-v2 -i RO_VPD:${RO_VPD} -r /dev/null
  ${FLASHROM_CMD} -p ft2232_spi:type=servo-v2 -i RW_VPD:${RW_VPD} -r /dev/null
  ${FLASHROM_CMD} -p ft2232_spi:type=servo-v2 -i GBB:${GBB} -r /dev/null
  ${DUT_CONTROL_CMD} spi2_vref:off spi2_buf_en:off spi2_buf_on_flex_en:off

  #Generarate csv file
  ${RMA_CREATE_CSV_CMD} --ro_vpd "${RO_VPD}" \
                        --rw_vpd "${RW_VPD}" \
                        --gbb "${GBB}" \
                        -r "${rma_number}" \
                        -o "${OUTPUT_DIR}"
  local result=$?
  rm -rf "${TMPDIR}"
  return ${result}
}

function flash_firmware() {
  #Flash new system firmware
  ${DUT_CONTROL_CMD} spi2_vref:pp3300 spi2_buf_en:on spi2_buf_on_flex_en:on \
                     spi_hold:off cold_reset:on
  ${FLASHROM_CMD} -p ft2232_spi:type=servo-v2 --wp-disable
  ${FLASHROM_CMD} --noverify -p ft2232_spi:type=servo-v2 \
                  -w /usr/local/rma/firmware/nv_image-link.bin
  ${DUT_CONTROL_CMD} spi2_vref:off spi2_buf_en:off spi2_buf_on_flex_en:off
}

function reflash() {

  local rma_number="$1"
  servod_is_running || fail \
    "servod is not running please start it by running 'start servod'."

  servo_is_connected || fail \
    "Error communicating with servo." \
    "Please check connections and/or restart servod."

  dut_is_alive || fail \
    "Error communicating with DUT. Check flex cable."

  write_protect_is_disabled || fail \
    "Write protect is enabled. Remove the write protect screw and try again."

  flash_ec || fail "Error while reflashing EC." \
                   "Please plug in an AC adaptor and try again."

  save_volitile_data "${rma_number}" "${TMPDIR}" || fail
  flash_firmware
  show_ok
  echo "Please detach the flex cable and reinsert the write protect screw."
}

function main() {
  while true; do
    echo
    read -p "Enter RMA number: " rma_number
    if [[ ! ${rma_number} =~ RMA[0-9]{8} ]] ; then
      echo "Invalid RMA number."
      echo "Must be like RMAxxxxxxxx where the x's are numbers"
      echo "Example: RMA12345678."
      continue
    fi
    reflash "${rma_number}"
  done
}
main
