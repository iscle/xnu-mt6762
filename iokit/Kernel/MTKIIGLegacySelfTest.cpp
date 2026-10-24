/* Opt-in DEVELOPMENT-only validation of real generated Invoke entry points.
 * No device I/O, object creation, generated-method replacement, or ABI stubs.
 */
#if defined(ARM64_BOARD_CONFIG_MT6762) && (DEVELOPMENT || DEBUG)
#include <IOKit/IOMemoryDescriptor.h>
#include <DriverKit/OSAction.h>
#include <DriverKit/IODispatchSource.h>
#include <kern/locks.h>
#include <libkern/libkern.h>
#include <pexpert/pexpert.h>
#include <sys/errno.h>
#include <sys/sysctl.h>

extern "C" { SYSCTL_DECL(_kern_redwood); }
LCK_GRP_DECLARE(mtk_iig_test_group, "mtk_iig_test");
LCK_MTX_DECLARE(mtk_iig_test_lock, &mtk_iig_test_group);
static int test_result, test_cases, handler_calls;
static unsigned work_reply_mutation;
static const uint64_t guard_value = 0x8d1374a6f2b05ce9ULL;

/* Independently described legacy wire buffers, not generated private types. */
#pragma pack(push, 4)
struct TestRequest {
    IORPCMessageMach mach;
    mach_msg_port_descriptor_t object_descriptor;
    IORPCMessage content;
    OSObjectRef object;
};
struct TestReply {
    IORPCMessageMach mach;
    IORPCMessage content;
    _IOMemoryMapPrivateState state;
};
struct GuardedReply {
    uint64_t before;
    TestReply reply;
    uint64_t after;
};
struct TestWorkRequest {
    TestRequest base;
    bool synchronous;
    unsigned char reserved[7];
};
struct TestWorkReply {
    TestRequest work;
    unsigned char spare[40];
};
struct GuardedWorkReply {
    uint64_t before;
    TestWorkReply reply;
    uint64_t after;
};
struct WorkWithoutDescriptor {
    IORPCMessageMach mach;
    IORPCMessage content;
    OSObjectRef object;
};
#pragma pack(pop)
static_assert(sizeof(IORPC) == 24, "test targets legacy IORPC");
static_assert(sizeof(IORPCMessageMach) == 36, "kernel Mach header and body ABI");
static_assert(sizeof(TestRequest) == 84, "review raw kernel request ABI");
static_assert(sizeof(TestReply) == 92, "review raw kernel reply ABI");
static_assert(sizeof(TestWorkRequest) == 92, "CheckForWork request ABI");
static_assert(sizeof(TestWorkReply) == 124, "CheckForWork minimum reply capacity");

static bool record(bool passed)
{
    ++test_cases;
    if (!passed) test_result = -test_cases;
    return passed;
}

static kern_return_t copy_state_handler(OSMetaClassBase *target, _IOMemoryMapPrivateState *state)
{
    ++handler_calls;
    if (target || !state) return kIOReturnBadArgument;
    const _IOMemoryMapPrivateState value = { 0x1122334455667788ULL,
        0x8877665544332211ULL, 0x2468ace013579bdfULL, 0x13579bdf2468ace0ULL };
    /* The wire reply has four-byte alignment; do not add a test-handler
     * assumption that this naturally aligned C++ struct pointer is eight. */
    memcpy(state, &value, sizeof(value));
    return kIOReturnSuccess;
}

static void aborted_handler(OSMetaClassBase *target)
{
    handler_calls += target ? 1000 : 1;
}

static TestRequest pristine_request(void)
{
    TestRequest r = {};
    r.mach.msgh.msgh_id = kIORPCVersion190615;
    r.mach.msgh.msgh_size = sizeof(r);
    r.mach.msgh_body.msgh_descriptor_count = 1;
    r.object_descriptor.type = MACH_MSG_PORT_DESCRIPTOR;
    r.content.msgid = IOMemoryMap__CopyState_ID;
    r.content.objectRefs = 1;
    return r;
}

/* Construct request-shaped asynchronous replies without dereferencing or
 * invoking their object reference. CheckForWork_Invoke validates this output;
 * its separate outgoing wrapper is covered by counted source-order checks. */
static kern_return_t work_handler(OSMetaClassBase *target, IORPC rpc, bool synchronous)
{
    ++handler_calls;
    if (target || synchronous || !rpc.reply || rpc.replySize < sizeof(TestWorkReply))
        return kIOReturnBadArgument;
    TestWorkReply reply = {};
    reply.work = pristine_request();
    reply.work.content.msgid = OSAction_Aborted_ID;
    reply.work.content.flags = kIORPCMessageOneway;
    reply.work.object = 0x13579bdf; /* Sentinel only; never an object target. */
    switch (work_reply_mutation) {
    case 0: break; /* Complete one-reference asynchronous request. */
    case 1: /* Valid bounded header, no reference bytes or logical reference. */
        reply.work.content.objectRefs = 0;
        reply.work.mach.msgh.msgh_size = __builtin_offsetof(TestRequest, object);
        break;
    case 2: /* Claims a reference but ends immediately before its storage. */
        reply.work.mach.msgh.msgh_size = __builtin_offsetof(TestRequest, object);
        break;
    case 3: reply.work.mach.msgh.msgh_id = kIORPCVersion190615Reply; break;
    case 4: reply.work.content.flags = 0; break;
    case 5: { /* Structurally bounded reference, but zero Mach descriptors. */
        WorkWithoutDescriptor no_descriptor = {};
        no_descriptor.mach.msgh.msgh_id = kIORPCVersion190615;
        no_descriptor.mach.msgh.msgh_size = sizeof(no_descriptor);
        no_descriptor.content = reply.work.content;
        no_descriptor.object = reply.work.object;
        memcpy(&reply, &no_descriptor, sizeof(no_descriptor));
        break;
    }
    case 6: reply.work.mach.msgh_body.msgh_descriptor_count = UINT32_MAX; break;
    case 7: reply.work.content.objectRefs = 0; break; /* Bytes alone are not a reference. */
    case 8: reply.work.mach.msgh.msgh_size = rpc.replySize + 1; break;
    default: return kIOReturnBadArgument;
    }
    memcpy(rpc.reply, &reply, sizeof(reply));
    return kIOReturnSuccess;
}

static bool work_tests(void)
{
    TestWorkRequest request = {};
    request.base = pristine_request();
    request.base.content.msgid = IODispatchSource_CheckForWork_ID;
    request.base.mach.msgh.msgh_size = sizeof(request);
    GuardedWorkReply guarded;
    IORPC rpc = { &request.base.mach, &guarded.reply.work.mach, sizeof(request), sizeof(guarded.reply) };
    for (work_reply_mutation = 0; work_reply_mutation < 9; ++work_reply_mutation) {
        memset(&guarded, 0xa5, sizeof(guarded));
        guarded.before = guarded.after = guard_value;
        handler_calls = 0;
        const kern_return_t expected = work_reply_mutation ? kIOReturnIPCError : kIOReturnSuccess;
        const kern_return_t result = IODispatchSource::CheckForWork_Invoke(rpc, nullptr, work_handler);
        if (!record(result == expected && handler_calls == 1 &&
                    guarded.before == guard_value && guarded.after == guard_value)) return false;
    }
    work_reply_mutation = 0;
    for (unsigned mutation = 0; mutation < 3; ++mutation) {
        memset(&guarded, 0xa5, sizeof(guarded));
        guarded.before = guarded.after = guard_value;
        const GuardedWorkReply before = guarded;
        rpc = { &request.base.mach, &guarded.reply.work.mach, sizeof(request), sizeof(guarded.reply) };
        if (mutation == 0) --rpc.sendSize;
        if (mutation == 1) rpc.reply = nullptr;
        if (mutation == 2) --rpc.replySize;
        handler_calls = 0;
        const kern_return_t result = IODispatchSource::CheckForWork_Invoke(rpc, nullptr, work_handler);
        if (!record(result == kIOReturnIPCError && handler_calls == 0 &&
                    memcmp(&guarded, &before, sizeof(guarded)) == 0)) return false;
    }
    return true;
}

static GuardedReply pristine_reply(void)
{
    GuardedReply r;
    memset(&r, 0xa5, sizeof(r));
    r.before = r.after = guard_value;
    return r;
}

static bool reply_correct(const GuardedReply& r)
{
    return r.before == guard_value && r.after == guard_value &&
        r.reply.mach.msgh.msgh_id == kIORPCVersion190615Reply &&
        r.reply.mach.msgh.msgh_size == sizeof(TestReply) &&
        r.reply.mach.msgh_body.msgh_descriptor_count == 0 &&
        r.reply.content.msgid == IOMemoryMap__CopyState_ID &&
        r.reply.content.objectRefs == 0 &&
        r.reply.state.length == 0x1122334455667788ULL &&
        r.reply.state.offset == 0x8877665544332211ULL &&
        r.reply.state.options == 0x2468ace013579bdfULL &&
        r.reply.state.address == 0x13579bdf2468ace0ULL;
}

static bool reject(const IORPC& rpc, GuardedReply& guarded)
{
    const GuardedReply before = guarded;
    handler_calls = 0;
    const kern_return_t result = IOMemoryMap::_CopyState_Invoke(rpc, nullptr, copy_state_handler);
    return record(result == kIOReturnIPCError && handler_calls == 0 &&
                  memcmp(&guarded, &before, sizeof(guarded)) == 0);
}

static void run_test(void)
{
    TestRequest request = pristine_request();
    GuardedReply guarded = pristine_reply();
    IORPC rpc = { &request.mach, &guarded.reply.mach, sizeof(request), sizeof(guarded.reply) };
    handler_calls = 0;
    kern_return_t result = IOMemoryMap::_CopyState_Invoke(rpc, nullptr, copy_state_handler);
    if (!record(result == kIOReturnSuccess && handler_calls == 1 && reply_correct(guarded))) return;

    /* Real generated outgoing methods use overlapping request/reply storage. */
    guarded = pristine_reply();
    memcpy(&guarded.reply, &request, sizeof(request));
    rpc.message = &guarded.reply.mach;
    handler_calls = 0;
    result = IOMemoryMap::_CopyState_Invoke(rpc, nullptr, copy_state_handler);
    if (!record(result == kIOReturnSuccess && handler_calls == 1 && reply_correct(guarded))) return;

    /* Exercise the valid four-byte wire alignment without an aligned cast. */
    alignas(8) unsigned char storage[sizeof(TestRequest) + 8];
    memcpy(storage + 4, &request, sizeof(request));
    rpc.message = reinterpret_cast<IORPCMessageMach *>(storage + 4);
    guarded = pristine_reply(); handler_calls = 0;
    result = IOMemoryMap::_CopyState_Invoke(rpc, nullptr, copy_state_handler);
    if (!record(result == kIOReturnSuccess && handler_calls == 1 && reply_correct(guarded))) return;

    rpc.message = nullptr;
    if (!reject(rpc, guarded)) return;
    rpc.message = &request.mach; rpc.reply = nullptr;
    if (!reject(rpc, guarded)) return;
    rpc.reply = &guarded.reply.mach;
    for (uint32_t size = 0; size < sizeof(request); ++size) {
        rpc.sendSize = size;
        if (!reject(rpc, guarded)) return;
    }
    rpc.sendSize = sizeof(request);
    for (uint32_t size = 0; size < sizeof(guarded.reply); ++size) {
        rpc.replySize = size;
        if (!reject(rpc, guarded)) return;
    }
    rpc.replySize = sizeof(guarded.reply);
    for (unsigned mutation = 0; mutation < 10; ++mutation) {
        request = pristine_request();
        switch (mutation) {
        case 0: request.mach.msgh.msgh_id = kIORPCVersion190615Reply; break;
        case 1: request.mach.msgh.msgh_size = sizeof(request) - 1; break;
        case 2: request.mach.msgh.msgh_size = sizeof(request) + 1; break;
        case 3: request.mach.msgh_body.msgh_descriptor_count = 0; break;
        case 4: request.mach.msgh_body.msgh_descriptor_count = UINT32_MAX; break;
        case 5: request.object_descriptor.type = MACH_MSG_OOL_PORTS_DESCRIPTOR; break;
        case 6: request.content.objectRefs = 0; break;
        case 7: request.content.objectRefs = UINT64_MAX; break;
        case 8: request.content.msgid ^= 1; break;
        case 9: request.mach.msgh.msgh_size = sizeof(IORPCMessageMach); break;
        }
        if (!reject(rpc, guarded)) return;
    }
    request = pristine_request();
    request.content.msgid = OSAction_Aborted_ID;
    request.content.flags = kIORPCMessageOneway;
    rpc.reply = nullptr; rpc.replySize = 0;
    handler_calls = 0;
    result = OSAction::Aborted_Invoke(rpc, nullptr, aborted_handler);
    if (!record(result == kIOReturnSuccess && handler_calls == 1)) return;
    request.content.objectRefs = 2;
    handler_calls = 0;
    result = OSAction::Aborted_Invoke(rpc, nullptr, aborted_handler);
    if (!record(result == kIOReturnIPCError && handler_calls == 0)) return;
    if (!work_tests()) return;
    test_result = 1;
}

static int test_sysctl SYSCTL_HANDLER_ARGS
{
    int enabled = 0;
    if (!PE_parse_boot_argn("mt6762_iig_selftest", &enabled, sizeof(enabled)) || enabled != 1)
        return ENOTSUP;
    if (req->newptr) return EPERM;
    lck_mtx_lock(&mtk_iig_test_lock);
    if (!test_result) run_test();
    int value = arg2 ? test_cases : test_result;
    lck_mtx_unlock(&mtk_iig_test_lock);
    return sysctl_handle_int(oidp, &value, 0, req);
}
SYSCTL_PROC(_kern_redwood, OID_AUTO, mt6762_iig_test_result,
    CTLTYPE_INT | CTLFLAG_RD | CTLFLAG_LOCKED, nullptr, 0, test_sysctl, "I",
    "Opt-in actual generated Invoke test: 1 passed, negative failing case; disabled ENOTSUP");
SYSCTL_PROC(_kern_redwood, OID_AUTO, mt6762_iig_test_cases,
    CTLTYPE_INT | CTLFLAG_RD | CTLFLAG_LOCKED, nullptr, 1, test_sysctl, "I",
    "Completed one-shot actual generated Invoke test cases");
#endif
