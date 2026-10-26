Physical presentation after capture36
=====================================

The retained Image41/kernel54 capture reaches the original Apple window server,
SpringBoard's system-shell connection and native touch events in backboardd.
Its framebuffer still contains the kernel text console. Artifact hashes and
bounded observations are in desktop-capture35-36-evidence.json. These milestones
do not establish a visible desktop.

A concrete console lifecycle error exists in the captured source. The physical
profile2 initialization acquires an enabled text console. MiniFB's first surface
previously called only kPEGraphicsMode, which changes console intent without
disabling its writer. kPEReleaseScreen performs gc_enable(FALSE). Consequently
later text can overwrite graphics. This is not yet proof that console writes
are the sole presentation blocker: even MiniFB registration IOLog lines are
absent from the retained capture, so lack of swap IOLog lines cannot prove that
no swaps occurred.

The migrated MT6762 path now releases the console and selects graphics mode
inside drawLayer, after validating source geometry, panel intersection and
backing pixels. The existing blanked and pixel-format gates remain before this
path. Invalid/offscreen surfaces retain the diagnostic console. Other boards
retain their previous handoff. No screen reacquisition, progress overlay,
scanout reprogramming or new hardware ownership is introduced.

Bounded kprintf records identify service registration, the first eight valid-size
SwapEnd submissions, first eight presenter entries including blank state, first
sixteen nonzero surface lookups, and the one-time first drawable layer handoff
and copy completion. The counters use the existing queue/presentation locks.
The kprintf serial callback also writes the retained loader log; normal diagnostic
serial enablement and RAM preservation still apply. A copy-complete marker is
software evidence, not panel or Apple-content proof.

Validation::

  python3 tools/mt6762/physical/test_present_console.py

Two host tests pass, including compilation/execution of the actual drawLayer
method for MT6762 and non-MTK. Host stubs check command order before row copying,
one-time handoff, malformed/overflowing/invisible input rejection, absent backing,
the existing full-surface fallback and split-helper branch. They do not emulate
IOKit scheduling or physical scanout. Kernel build and physical validation of
this change remain pending.
