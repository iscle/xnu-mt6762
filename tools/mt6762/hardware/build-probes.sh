#!/bin/sh
# Explicit iOS cross compiler, SDK, signer and fresh output directory required.
# Never edits Apple executables or images.
set -eu
if [ "$#" -ne 1 ]; then echo "usage: IOS_CC=... IOS_SDK=... LDID=... $0 NEW_OUTPUT_DIRECTORY" >&2; exit 2; fi
: "${IOS_CC:?set IOS_CC to the iOS clang driver}"
: "${IOS_SDK:?set IOS_SDK to the iPhoneOS SDK directory}"
: "${LDID:?set LDID to the project signing tool}"
source_dir=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
output_dir=$1
mkdir -- "$output_dir"
for helper in backlight_probe backlight_request display_power_probe battery_probe; do
    case "$helper" in battery_probe) source_file="$source_dir/power/$helper.c";;
        *) source_file="$source_dir/display-touch/$helper.c";; esac
    "$IOS_CC" -arch arm64 -isysroot "$IOS_SDK" -O1 -Wall -Wextra -Werror \
        -framework CoreFoundation -framework IOKit -o "$output_dir/$helper" "$source_file"
    case "$helper" in backlight_request|display_power_probe)
        "$LDID" "-S$source_dir/display-touch/backlight_request.entitlements" "$output_dir/$helper";;
        *) "$LDID" -S "$output_dir/$helper";; esac
done
