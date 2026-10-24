/* Exercise actual xnu-8796 IORPC declarations using its standalone ABI types. */
#include <cassert>
#include <cstdint>
#include <cstring>
#include <cstdio>
#include <sys/mman.h>
#include <unistd.h>
typedef int kern_return_t;
#define KERNEL 1
#define DRIVERKIT_PRIVATE 1
#define XNU_PLATFORM_DriverKit 1
#include "MTKIIGLegacy.h"

#pragma pack(push, 4)
struct Request {
	IORPCMessageMach mach;
	mach_msg_port_descriptor_t object;
	mach_msg_ool_descriptor_t data;
	IORPCMessage header;
	OSObjectRef refs[2];
	uint64_t scalar;
};
#pragma pack(pop)

int main()
{
	static_assert(sizeof(mach_msg_port_descriptor_t) == 16, "kernel port ABI");
	static_assert(sizeof(mach_msg_ool_descriptor_t) == 16, "kernel OOL ABI");
	Request pristine = {};
	pristine.mach.msgh.msgh_id = kIORPCVersion190615;
	pristine.mach.msgh.msgh_size = sizeof(pristine);
	pristine.mach.msgh_body.msgh_descriptor_count = 2;
	pristine.object.type = MACH_MSG_PORT_DESCRIPTOR;
	pristine.data.type = MACH_MSG_OOL_DESCRIPTOR;
	pristine.header.msgid = 0x1122334455667788ULL;
	pristine.header.objectRefs = 2;
	pristine.refs[0] = 1;
	pristine.refs[1] = 2;
	Request test = pristine;
	IORPC rpc = { &test.mach, nullptr, sizeof(test), 0 };
	auto accepts = [&]() { return mtk_iig_legacy_request(rpc, sizeof(test),
	    __builtin_offsetof(Request, header), 2, pristine.header.msgid); };
	assert(accepts());
	assert(mtk_iig_legacy_message(rpc) == &test.header);
	for (uint32_t capacity = 0; capacity < sizeof(test); ++capacity) {
		rpc.sendSize = capacity;
		assert(!accepts());
	}
	rpc.sendSize = sizeof(test);
	for (uint32_t size = 0; size < sizeof(test); ++size) {
		test.mach.msgh.msgh_size = size;
		assert(!accepts());
	}
	test = pristine;
	test.mach.msgh.msgh_size++;
	assert(!accepts());
	test = pristine;
	test.header.msgid++;
	assert(!accepts());
	test = pristine;
	test.header.objectRefs = UINT64_MAX;
	assert(!accepts());
	test = pristine;
	test.mach.msgh_body.msgh_descriptor_count = UINT32_MAX;
	assert(!accepts());
	test = pristine;
	test.data.type = 2;
	assert(!accepts());
	test = pristine;
	test.mach.msgh.msgh_id = kIORPCVersion190615Reply;
	assert(!accepts());
	test = pristine;
	assert(!mtk_iig_legacy_request(rpc, sizeof(test), 0, 2, test.header.msgid));
	assert(!mtk_iig_legacy_request(rpc, UINT32_MAX, UINT32_MAX, 2, test.header.msgid));
	IORPC reply = {nullptr, &test.mach, 0, sizeof(test)};
	assert(mtk_iig_legacy_message(reply, true) == &test.header);
	assert(!mtk_iig_legacy_message(reply));
	reply.replySize--;
	assert(!mtk_iig_legacy_message(reply, true));
	IORPC overflow = {reinterpret_cast<IORPCMessageMach *>(UINTPTR_MAX - 3), nullptr, 100, 0};
	assert(!mtk_iig_legacy_message(overflow));
	IORPC null = {};
	assert(!mtk_iig_legacy_message(null));

	/* Place each 4-byte-aligned truncated prefix directly before PROT_NONE.
	 * A read beyond the advertised accessible capacity faults the process. */
	const size_t page = static_cast<size_t>(sysconf(_SC_PAGESIZE));
	auto *mapping = static_cast<unsigned char *>(mmap(nullptr, 2 * page,
	    PROT_READ | PROT_WRITE, MAP_PRIVATE | MAP_ANONYMOUS, -1, 0));
	assert(mapping != MAP_FAILED);
	assert(mprotect(mapping + page, page, PROT_NONE) == 0);
	for (uint32_t capacity = 0; capacity <= sizeof(test); capacity += 4) {
		auto *position = mapping + page - capacity;
		memcpy(position, &pristine, capacity);
		IORPC bounded = {reinterpret_cast<IORPCMessageMach *>(position), nullptr, capacity, 0};
		assert(bool(mtk_iig_legacy_message(bounded)) == (capacity == sizeof(test)));
		/* Also malformed self-reported sizes and descriptor counts, with
		 * the physical boundary fixed to the advertised capacity. */
		if (capacity >= sizeof(IORPCMessageMach)) {
			bounded.message->msgh.msgh_size = capacity;
			bounded.message->msgh_body.msgh_descriptor_count = UINT32_MAX;
			assert(!mtk_iig_legacy_message(bounded));
		}
	}
	/* Content may be only 4-byte aligned; retain packed-member access. */
	auto *unaligned = mapping + 4;
	memcpy(unaligned, &pristine, sizeof(pristine));
	IORPC four = {reinterpret_cast<IORPCMessageMach *>(unaligned), nullptr, sizeof(pristine), 0};
	assert(mtk_iig_legacy_message(four)->msgid == pristine.header.msgid);
	assert(munmap(mapping, 2 * page) == 0);
	printf("PASS legacy24 bounds: request=%zu content_offset=%zu; truncation, guard-page, descriptor, version, alignment, reply-buffer checks\n",
	    sizeof(Request), __builtin_offsetof(Request, header));
}
