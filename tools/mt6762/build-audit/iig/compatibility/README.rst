Single-interface IIG 440 compatibility audit
============================================

This bounded comparison reads genuine Xcode 26.6 diagnostic output for the
original xnu-8796.121.2 IOUserClient.iig, the existing MacOSX13.3 SDK header
marked DriverKit-256.100.8, and current xnu8796 transport sources. It does not
import generated code, modify Apple userspace, or establish complete wire ABI
compatibility. The exact file hashes and source locations are in
``iouserclient-440-vs-256.json``; the read-only comparison script reproduces it.

Observed agreement
------------------

All six IOUserClient method IDs match exactly, including KernelCompletion and
_ExternalMethod. No method ID was added, removed or changed. The new wrappers
still emit kIORPCVersion190615 requests and kIORPCVersion190615Reply replies.
They still allocate complete Msg_With_Content/Rpl_With_Content buffers, set
Mach descriptor counts and objectRefs, and serialize the original interface's
arguments. These facts support investigating compatibility; they do not prove
all argument offsets, packing, bounds, object ownership or 17-class behavior.

The visible kernel header declaration differences replace array typedef
parameters with their pointer spelling (for example const
IOUserClientScalarArray becomes const unsigned long long *). In the ARM64
interface, uint64_t is unsigned long long and function array parameters decay
to pointers, so these specific changes are not an extra argument or array-size
change. Most added class/metaclass boilerplate is guarded by !KERNEL. The old
SDK supplies headers, not an authentic old generated implementation, so a full
old/new generated wire-struct byte comparison is unavailable from these inputs.

Actual incompatibility
----------------------

The original IORPC has two pointers and two uint32_t sizes: 24 bytes on ARM64.
Generated 440 invocation unions add a kernelContent pointer after those fields,
and kernel code directly reads rpc.kernelContent in Dispatch and Invoke. It
also sets that field in outgoing aggregate initializers. A corresponding
extended IORPC would be 32 bytes. This is an internal by-value C++ ABI change;
retaining the type's name does not make old precompiled kernel callers compatible.

The original incoming IOUserServer server path creates a four-field IORPC and
passes it through kernelDispatch. Both kernelDispatch and OSMetaClassBase::Invoke
already parse the content using IORPCMessageFromMach, but neither initializes a
separate kernelContent pointer. Appending a field alone therefore leaves a null
pointer in incoming calls and is insufficient. The generated kernel dispatch
and Invoke code dereference that pointer.

Possible source compatibility work, still unvalidated
-----------------------------------------------------

A proposed port must choose explicitly between changing the internal IORPC ABI
and adapting newly generated source to the original transport contract. The
latter could retain the four-field IORPC and derive content through the existing
validated Mach-message parser for dispatch instead of relying on the new pointer.
For Invoke, retaining the complete packed Msg_With_Content type and accessing
message->content preserves the compiler's packed-member access information. A
cast from the wire content address to the naturally aligned Content type can
lose that information and introduce alignment undefined behavior; it is not a
substitute for auditing packed access. Outgoing wrappers already allocate full
contiguous Msg_With_Content buffers in the inspected class. This is an
engineering hypothesis, not an implemented transform or accepted output.
Do not simply remove the kernelContent rejection or add an uninitialized field.

Before accepting either approach, examine all 17 genuine outputs, prove matching
message IDs and packed wire layouts, preserve message-size/object-reference
checks and pointer alignment, account for local/supermethod/asynchronous paths,
then compile/link, re-audit exports and exercise actual dispatch/Invoke behavior.
An equivalent ordinary RPC transport must still reject malformed/truncated
messages. The userspace IPSW binaries remain precompiled and unmodified.

The strict Linux Xcode 15 replay path remains unchanged and rejects diagnostic
Xcode 26 output. No claim here upgrades a successful generator invocation into
a successfully compiled kernel or verified real-device driver.

All-interface follow-up
-----------------------

compare_all.py extends the method-ID comparison to all17 original interfaces.
all17-440-vs-256.json records all95 method IDs, exact header/interface hashes
and generated Invoke inventories: every ID matches. The old SDK does not
contain the original generated implementation/wire-struct definitions, so this
is explicitly not a complete old/new wire-layout equivalence proof. The
source transform and bounded parser live under ../../../iig/; target build and
real handler execution remain separate evidence.
