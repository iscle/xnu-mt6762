#!/bin/sh
set -eu
source_dir=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
test_dir=$(mktemp -d)
trap 'rm -rf -- "$test_dir"' EXIT HUP INT TERM
compiler=${CC:-cc}
for test_name in test_axs_touch test_axs_touch_state test_display_core test_apple_backlight; do
    "$compiler" -std=c11 -Wall -Wextra -Werror "$source_dir/$test_name.c" -o "$test_dir/$test_name"
    "$test_dir/$test_name"
done
"$compiler" -std=c11 -Wall -Wextra -Werror -fsyntax-only "$source_dir/axs15260_panel.h"
