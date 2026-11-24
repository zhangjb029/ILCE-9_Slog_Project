#!/bin/sh
# A9_V5_PACKAGE_ID=7aa8d1e6060d34b0
# Stage a fixed local bundle into RAM. No SD access or monitor IPC at startup.
set -uf
umask 077
export PATH=/usr/bin:/bin:/sbin:/usr/sbin
BB=/bin/busybox
RAM=/tmp_bt
SOURCE=/tmp/a9-film-boot-v7.tar
COPY=$RAM/a9-film-boot.copy
STAGE=$RAM/a9-film-boot-stage
LOCK=$RAM/a9-film-local-boot.lock
BOOTLOG=$RAM/a9-film-boot.log
BUNDLE_BYTES=204800
test -d "$RAM" && test ! -L "$RAM" || exit 1
test ! -e "$BOOTLOG" && test ! -L "$BOOTLOG" || exit 1
if ! ( set -C; : > "$BOOTLOG" ) 2>/dev/null; then
    test -r /proc/mounts || exit 1
    _ram_mounted=0
    _msrc=""
    _mtgt=""
    _mrest=""
    while read -r _msrc _mtgt _mrest; do
        if test "${_mtgt:-}" = "$RAM"; then
            _ram_mounted=1
            break
        fi
    done < /proc/mounts
    test "$_ram_mounted" = 0 || exit 1
    "$BB" mount -t tmpfs -o size=2048k tmpfs "$RAM" || exit 1
    test ! -e "$BOOTLOG" && test ! -L "$BOOTLOG" || exit 1
    ( set -C; : > "$BOOTLOG" ) 2>/dev/null || exit 1
fi
exec >> "$BOOTLOG" 2>&1 || exit 1
echo "FILM_LOCAL_BOOT_BEGIN package=7aa8d1e6060d34b0 pid=$$ version=V3.9-SSLF"
fail() { echo "FILM_LOCAL_BOOT_FAIL stage=$1"; exit 1; }
hash_is() {
    test -f "$1" && test ! -L "$1" || return 1
    if hash_line=$("$BB" sha256sum "$1" 2>/dev/null); then
        test "${hash_line%% *}" = "$2"
        return $?
    fi
    hash_line=$(/usr/bin/openssl dgst -sha256 "$1" 2>/dev/null) || return 1
    test "${hash_line##* }" = "$2"
}
disabled() {
    test -e /tmp/disable_hook || test -e "$RAM/a9-film.DISABLE" ||
        test -e "$RAM/a9-film-capture.stop"
}
gate() {
    ! disabled && test -r /proc/mounts || return 1
    while read -r source target rest; do
        case "$source" in /dev/mmca*|/dev/mmcblk*) return 1;; esac
    done < /proc/mounts
}
phase() { { echo "phase=$1"; echo "pid=$$"; echo "package=7aa8d1e6060d34b0"; } > "$LOCK/manifest"; }
if disabled; then echo FILM_LOCAL_BOOT_DISABLED; exit 0; fi
gate || fail sd_linux_mounted
test -f "$RAM/ae.lock" && test ! -L "$RAM/ae.lock" || fail missing_constructor_lock
for path in "$COPY" "$STAGE" "$RAM/a9-film-runtime.lock"; do
    test ! -e "$path" && test ! -L "$path" || fail outstanding_operation_or_copy
done
hash_is "$SOURCE" acd5a6ceac2e5f821dd4f5f6738ffce2d4d1e968cc232155308ce7a4cb850ddc || fail local_bundle_pin
"$BB" mkdir "$LOCK" || fail existing_boot
phase local_copy || fail phase
# Noclobber prevents replacing a concurrently created file or symlink.
set -C
"$BB" cat "$SOURCE" > "$COPY" || fail local_copy
set +C
hash_is "$COPY" acd5a6ceac2e5f821dd4f5f6738ffce2d4d1e968cc232155308ce7a4cb850ddc || fail bundle_hash
byte_line=$("$BB" wc -c < "$COPY") || fail bundle_size
set -- $byte_line
test "$#" = 1 && test "$1" = "$BUNDLE_BYTES" || fail bundle_size
gate || fail extract_gate
"$BB" mkdir "$STAGE" || fail stage_directory
"$BB" tar -xf "$COPY" -C "$STAGE" || fail extract
hash_is "$STAGE/prepare.sh" beaf206f603fc138c6fc55aa903646b10a96cc86eea37b7459b4b042183b1fcd || fail prepare_pin
phase prepare || fail phase
/bin/sh "$STAGE/prepare.sh"
prepare_rc=$?
if test "$prepare_rc" = 10; then echo FILM_LOCAL_BOOT_DISABLED; exit 0; fi
test "$prepare_rc" = 0 || fail prepare
gate && hash_is "$RAM/a9-film-runtime-start.sh" 69a843facc32d8dda20c024e926c3afd4ab9348eb6b27d5664dd58380aa65487 || fail runtime_pin
hash_is "$COPY" acd5a6ceac2e5f821dd4f5f6738ffce2d4d1e968cc232155308ce7a4cb850ddc && "$BB" rm "$COPY" || fail archive_release
phase runtime || fail phase
echo "FILM_LOCAL_BOOT_STAGED package=7aa8d1e6060d34b0 native_sd_read=0 raw_sd_mount=0"
exec /bin/sh "$RAM/a9-film-runtime-start.sh"
