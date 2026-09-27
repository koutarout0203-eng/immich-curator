#!/bin/sh
set -eu

if [ "$(id -u)" -ne 0 ]; then
  echo "Run this script with sudo on TrueNAS." >&2
  exit 1
fi

SOURCE_DIR=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
PARENT_DATASET=${CURATOR_PARENT_DATASET:-tanico-nas/apps}
CURATOR_DATASET=${CURATOR_DATASET:-${PARENT_DATASET}/immich-curator}
TARGET_ROOT=${CURATOR_TARGET_ROOT:-/mnt/tanico-nas/apps/immich-curator}
TARGET_DATA=${TARGET_ROOT}/data
APP_UID=${CURATOR_UID:-10001}
APP_GID=${CURATOR_GID:-10001}

for required in compose.yaml .env.example home-periods.json; do
  if [ ! -f "${SOURCE_DIR}/${required}" ]; then
    echo "Missing deployment file: ${SOURCE_DIR}/${required}" >&2
    exit 1
  fi
done

if ! zfs list -H -o name "${PARENT_DATASET}" >/dev/null 2>&1; then
  zfs create "${PARENT_DATASET}"
fi

if ! zfs list -H -o name "${CURATOR_DATASET}" >/dev/null 2>&1; then
  zfs create "${CURATOR_DATASET}"
fi

install -d -m 0750 -o root -g root "${TARGET_ROOT}"
install -d -m 0750 -o "${APP_UID}" -g "${APP_GID}" "${TARGET_DATA}"
install -m 0644 -o root -g root "${SOURCE_DIR}/compose.yaml" "${TARGET_ROOT}/compose.yaml"
install -m 0644 -o "${APP_UID}" -g "${APP_GID}" "${SOURCE_DIR}/home-periods.json" "${TARGET_DATA}/home-periods.json"

if [ ! -e "${TARGET_ROOT}/.env" ]; then
  install -m 0600 -o root -g root "${SOURCE_DIR}/.env.example" "${TARGET_ROOT}/.env"
fi

echo "Prepared ${CURATOR_DATASET} at ${TARGET_ROOT}."
echo "Next: edit ${TARGET_ROOT}/.env as root, then run the documented probe and one-shot sync."
