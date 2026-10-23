Reproducing the local MT6762 QEMU experiment
==========================================

These eight patches reproduce the local research machine used for MT6762
bring-up. They contain source code and documentation only: no phone firmware,
iOS files, credentials, personal partitions, or built binaries.

Source provenance
-----------------

* Upstream: https://github.com/qemu/qemu
* Exact base: ``b6c4b7e86dec12d07f5cac65265b986d38ee9002``
* Original local commits:
  ``90c27193d001c9fe2d4f45f76c490c076a83ba5b``,
  ``a6619bd46a471be75e626f46defa61d23017387f``,
  ``afcfb434f2ead1165e6a23ca9828c3cd414b1f21``,
  ``dafbf7f83d81cea79804ec731a6214a47e53d646``,
  ``6c4cfc34f2c08da2bb709be5ba8a3224152273bf``,
  ``1cefe6067521f188fffbe2070bd520501a8c60fe``,
  ``63ec9fcb45cb0cf59214a3d2b676f408d724cf62`` and
  ``78122652f1258b3900d7fd721c9b1df06d4122d4``.
* Resulting Git tree: ``aafff1a6302dbf3199b1c4de937899f384831435``.

``apply.sh`` verifies the patch SHA-256 hashes, fetches that exact upstream
commit, applies the patch series in order, and verifies the final tree.
Recreated commit hashes can differ because committer identity/time differ;
the source tree must match exactly.

This is AI-assisted local experimental code. It is not intended for upstream
submission. QEMU's ``AGENTS.md`` and ``docs/devel/code-provenance.rst`` permit
local experiments while excluding AI-generated upstream contributions.

No new hosted QEMU fork was created. GitHub CLI found an existing
``iscle/qemu`` fork when asked to create ``qemu-mt6762``. That existing
repository was not renamed, modified, or pushed to. The local checkout and
this patch series are the delivered fork; there is no new remote fork URL.

Apply and build
---------------

On Linux with GCC, Ninja, Python, pkg-config and QEMU's required development
libraries already available::

  tools/mt6762/qemu/apply.sh /absolute/path/to/new-qemu
  mkdir /absolute/path/to/new-qemu/build
  cd /absolute/path/to/new-qemu/build
  ../configure --target-list=aarch64-softmmu --disable-werror --disable-docs \
    --disable-gtk --disable-sdl --disable-opengl --disable-vnc \
    --disable-tools --disable-user --enable-tcg --disable-kvm
  ninja -j8 qemu-system-aarch64

The source's build system acquires its own pinned subprojects and Python
build dependencies. No system package installation is performed by these
instructions. The known original build used GCC on Fedora44 x86-64.

Stock-kernel experiment
-----------------------

Extract the kernel Image and the pure FDT from the supplied phone dump.
``boot.bin`` is Android boot-image v2, its kernel is gzip-compressed, and
its DTB component has an Android DT table wrapper. Passing that wrapper as
``-dtb`` is incorrect: extract the actual FDT entry first.

The validated inputs were:

* Image SHA-256:
  ``82b1919185a49f268a0f8e145a6714d6264c1f66918a90df0d763266147ead4b``
* Extracted FDT SHA-256:
  ``658e181d1a13d930dc09567883e734bdbd4579350c8332ff954a0ecbb2ed08fe``

Run a bounded experiment::

  timeout 15s ./qemu-system-aarch64 -M mt6762 -accel tcg -cpu cortex-a53 \
    -smp 8 -m 512M -display none -monitor none -serial stdio -no-reboot \
    -kernel /path/to/Image -dtb /path/to/boot.bin.dtb \
    -append 'console=ttyS0,921600n1 earlycon=uart8250,mmio32,0x11002000,921600n8 keep_bootcon ignore_loglevel loglevel=8 nokaslr maxcpus=1 panic=0'

The RAM size here is a deliberately small laboratory configuration matching
the unpatched static DTB placeholder. It is not the phone's installed RAM.
Later inspection of actual boot records establishes 6 GiB physical DRAM;
runtime reserved-memory layout still matters for real-device boot.

Observed boundary: the unmodified stock Linux4.19.191 Image reaches its init
kernel thread, accepts the log-store SRAM handoff, initializes CPU alternatives
and pinctrl, then panics in ``get_dfd_base()`` during ``dfd_init()`` because
TOPRGU/watchdog registers are not modeled. This is not a complete Android boot.
The timeout or QEMU exit code alone must never be used as a boot-success test.

XNU experiments use the same Cortex-A53 model with separately prepared RAM
segments and a Linux-Image-format trampoline. The QEMU generic loader can load
segments using ``-device loader,file=FILE,addr=ADDRESS,force-raw=on``. Do not
set ``cpu-num`` on those segment loaders: it would override the CPU's entry
PC. The trampoline is selected with ``-kernel`` and receives the normal
nonsecure EL1, MMU-off entry environment.

Model limitations
-----------------

By default only the documented early-boot resources are modeled. The UART lacks MediaTek
extension registers; interrupt-polarity storage assumes normalized QEMU device
IRQ lines; timer support covers the BSP's one-shot programming sequence.
There is no MTK clock/reset/power, eMMC, USB, GPU, display, touch, TEE, modem,
or complete boot-firmware emulation. Migration/snapshot completeness is not
implemented or validated. Generic QEMU loader RAM-backed experiments do not
establish real peripheral compatibility or a safe physical boot image.

Opt-in I2C/APDMA laboratory
---------------------------

The third patch adds ``-M mt6762,lab-i2c=on`` with recovered I2C0/I2C5 v2
registers, APDMA, clock-gate and read-only pad fixtures. Synthetic AXS and
PSC devices are explicitly opt-in; default stock-kernel behavior is unchanged.
``lab-touch-sequence`` and ``lab-i2c-fault`` exercise contacts and failures;
read-only ``lab-i2c-state`` counters support independent native guest evidence.

Run ``python3 tests/mt6762/test_lab_i2c.py --qemu build/qemu-system-aarch64
--dtb /path/to/boot.bin.dtb`` for FIFO/DMA boundary, IRQ, gate, error and
recovery tests. See ``docs/system/arm/mt6762.rst`` for the exact fixture
contents and omissions. Native XNU probes are documented in
``tools/mt6762/boot/native-probes.rst`` in the XNU fork. Model tests and native
guest execution are separate from physical-phone validation.

The fourth patch adds explicit ``lab-display`` register/PWM fixtures with
bounded framebuffer assertions, read-only pipeline state and injectable
power/readback faults. It does not emulate actual pixel scanout, DSI or a
panel. ``tests/mt6762/test_lab_display.py`` checks the fixture independently;
native driver probes are described in the same native-probes document.

The fifth patch adds independent ``lab-power`` and ``lab-sspm`` fixtures,
including delayed synthetic ADC conversions, key levels, wrapper failure
states, PLATFORM mailbox liveness and stale ownership checks. The tests
explicitly do not emulate calibrated battery state or CPU-DVFS firmware.

The sixth patch adds QMP ``lab-touch-frame`` for explicit synthetic packets
consumed through I2C/APDMA. ``test_lab_touch.py`` verifies exact DMA data,
malformed setter rejection, empty contacts and restoring fixture defaults.
The host ``touch_lab.py`` helper is packaged separately with XNU boot tools.

The seventh patch adds ``lab-pmic-thermal`` with synthetic calibration and
three independent PMIC conversions, timed READY transitions and scoped
freshness/calibration faults. It does not model CPU thermal control or DVFS.
``test_lab_thermal.py`` tests this fixture separately from native execution.

The eighth patch adds ``lab-gauge`` with a synthetic initialized snapshot
engine and counter progression. Its tests verify latch commands, failures
and rejected destructive writes. Calibration/current values are fixtures;
no battery capacity, SOC or lifetime behavior is modeled.
