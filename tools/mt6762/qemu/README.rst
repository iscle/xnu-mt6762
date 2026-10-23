Reproducing the local MT6762 QEMU experiment
==========================================

These two patches reproduce the local research machine used for MT6762
bring-up. They contain source code and documentation only: no phone firmware,
iOS files, credentials, personal partitions, or built binaries.

Source provenance
-----------------

* Upstream: https://github.com/qemu/qemu
* Exact base: ``b6c4b7e86dec12d07f5cac65265b986d38ee9002``
* Original local commits:
  ``90c27193d001c9fe2d4f45f76c490c076a83ba5b`` and
  ``a6619bd46a471be75e626f46defa61d23017387f``.
* Resulting Git tree: ``4e5d318d6b373e56f1df95ac66e8ae19ef6b7464``.

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

Only the documented early-boot resources are modeled. The UART lacks MediaTek
extension registers; interrupt-polarity storage assumes normalized QEMU device
IRQ lines; timer support covers the BSP's one-shot programming sequence.
There is no MTK clock/reset/power, eMMC, USB, GPU, display, touch, TEE, modem,
or complete boot-firmware emulation. Migration/snapshot completeness is not
implemented or validated. Generic QEMU loader RAM-backed experiments do not
establish real peripheral compatibility or a safe physical boot image.
