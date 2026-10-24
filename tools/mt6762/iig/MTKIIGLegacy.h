/* Bounded contiguous-message adapter for the 24-byte xnu-8796 IORPC ABI.
 * Candidate only: the generator's separate kernelContent ABI is not imported.
 * The caller must own accessible sendSize/replySize bytes for the duration of
 * dispatch. This checks message structure; it cannot validate arbitrary kernel
 * pointers or prevent concurrent mutation by a caller violating that contract.
 */
#ifndef MTK_IIG_LEGACY_H
#define MTK_IIG_LEGACY_H

#include <DriverKit/IORPC.h>

static_assert(sizeof(IORPC) == 24, "requires legacy arm64 IORPC ABI");
static_assert(sizeof(IORPCMessage) == 24, "unexpected content header");

/* reply_buffer selects storage only. CheckForWork returns a request in its
 * reply buffer, so both routes require the request protocol version. */
static inline IORPCMessage *
mtk_iig_legacy_message(const IORPC& rpc, bool reply_buffer = false)
{
	IORPCMessageMach *base = reply_buffer ? rpc.reply : rpc.message;
	const uint32_t capacity = reply_buffer ? rpc.replySize : rpc.sendSize;
	const uint32_t start = __builtin_offsetof(IORPCMessageMach, objects);
	const uintptr_t address = reinterpret_cast<uintptr_t>(base);
	if (!base || (address & 3) || capacity < start ||
	    address > UINTPTR_MAX - capacity) return nullptr;

	mach_msg_header_t header;
	mach_msg_body_t body;
	const unsigned char *bytes = reinterpret_cast<const unsigned char *>(base);
	__builtin_memcpy(&header, bytes, sizeof(header));
	__builtin_memcpy(&body, bytes + __builtin_offsetof(IORPCMessageMach, msgh_body), sizeof(body));
	if (header.msgh_id != kIORPCVersion190615 || header.msgh_size > capacity ||
	    header.msgh_size < start) return nullptr;
	uint32_t offset = start;
	for (uint32_t i = 0; i < body.msgh_descriptor_count; ++i) {
		/* The common type byte lives in the first 12 bytes of both supported
		 * descriptors. Copy into the declared port type to avoid bitfield
		 * offsets and unaligned typed reads. Kernel port descriptors are 16B. */
		mach_msg_port_descriptor_t prefix = {};
		static_assert(sizeof(prefix) >= 12, "unexpected descriptor layout");
		if (header.msgh_size - offset < 12) return nullptr;
		__builtin_memcpy(&prefix, bytes + offset, 12);
		uint32_t length;
		if (prefix.type == MACH_MSG_PORT_DESCRIPTOR) length = sizeof(mach_msg_port_descriptor_t);
		else if (prefix.type == MACH_MSG_OOL_DESCRIPTOR) length = sizeof(mach_msg_ool_descriptor_t);
		else return nullptr;
		if (length > header.msgh_size - offset) return nullptr;
		offset += length;
	}
	if (header.msgh_size - offset < sizeof(IORPCMessage)) return nullptr;
	IORPCMessage content;
	__builtin_memcpy(&content, bytes + offset, sizeof(content));
	if (content.objectRefs > (header.msgh_size - offset - sizeof(content)) / sizeof(OSObjectRef))
		return nullptr;
	return reinterpret_cast<IORPCMessage *>(address + offset);
}

static inline bool
mtk_iig_legacy_request(const IORPC& rpc, uint32_t full_size,
    uint32_t content_offset, uint64_t expected_refs, uint64_t expected_id)
{
	IORPCMessage *content = mtk_iig_legacy_message(rpc);
	if (!content || full_size > rpc.sendSize || content_offset > full_size ||
	    full_size - content_offset < sizeof(IORPCMessage) ||
	    reinterpret_cast<uintptr_t>(content) - reinterpret_cast<uintptr_t>(rpc.message) != content_offset)
		return false;
	/* The parser above proved alignment and bounds for these packed headers. */
	return rpc.message->msgh.msgh_size >= full_size &&
	       rpc.message->msgh_body.msgh_descriptor_count == expected_refs &&
	       content->objectRefs == expected_refs && content->msgid == expected_id;
}
#endif
