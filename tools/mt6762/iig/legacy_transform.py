#!/usr/bin/env python3
"""Create a separate, unapproved 24-byte IORPC candidate from pinned IIG440 output.

This is a narrowly reviewed source transform, not an IIG implementation. It
never edits its inputs, kernel sources or replay policy, and never builds code.
"""
import argparse
import hashlib
import json
from pathlib import Path
import re
import sys

PROFILE = Path(__file__).with_name("legacy440_profile.json")
HELPER = "MTKIIGLegacy.h"


def sha(data):
    return hashlib.sha256(data).hexdigest()


def replace(text, pattern, replacement, expected, counts, name):
    text, count = re.subn(pattern, replacement, text, flags=re.M)
    if count != expected:
        raise ValueError("%s: expected %d reviewed shapes, found %d" % (name, expected, count))
    counts[name] = count
    return text


def transform_impl(text, profile):
    """Only known complete pattern shapes; counts and pristine hashes gate CLI."""
    counts = {}
    inv = profile["invocations"]
    dispatch = profile["dispatch"]
    required = profile["reply_required"]
    special = profile["class"] == "IODispatchSource"
    interrupt = profile["class"] == "IOInterruptDispatchSource"
    if text.count("kernelContent") != profile["kernelContent"]:
        raise ValueError("unreviewed kernelContent inventory")
    text = replace(text,
        r"#ifdef KERNEL\n        const struct (\w+)_Msg \* message;\n#else /\* KERNEL \*/\n"
        r"        const struct \1_Msg_With_Content \* message;\n#endif /\* KERNEL \*/",
        r"        const struct \1_Msg_With_Content * message;", inv, counts, "invocation_message")
    text = replace(text,
        r"#ifdef KERNEL\n        const struct \w+_Msg_Content \* kernelContent;\n#endif /\* KERNEL \*/\n",
        "", inv, counts, "invocation_extra_slot")
    text = replace(text,
        r"#ifdef KERNEL\n#define MESSAGE_CONTENT\(__field\) \(messageContent->__field\)\n"
        r"#else /\* KERNEL \*/\n#define MESSAGE_CONTENT\(__field\) \(message->content\.__field\)\n#endif /\* KERNEL \*/",
        "#define MESSAGE_CONTENT(__field) (message->content.__field)",
        dispatch // 2, counts, "packed_member_macro")
    text = replace(text,
        r"#ifdef KERNEL\n    IORPCMessage \* msg = rpc\.kernelContent;\n#else /\* KERNEL \*/\n"
        r"    IORPCMessage \* msg = IORPCMessageFromMach\(rpc\.message, false\);\n#endif /\* KERNEL \*/",
        "    IORPCMessage * msg = mtk_iig_legacy_message(rpc);\n"
        "    if (!msg) return (kIOReturnIPCError);", dispatch, counts, "dispatch_bounds")
    text = replace(text,
        r"#ifdef KERNEL\n    IORPC rpc = \{ ([^\n]+), \.kernelContent = &buf\.msg\.content\.__hdr \};\n"
        r"#else /\* KERNEL \*/\n    IORPC rpc = \{ \1 \};\n#endif /\* KERNEL \*/",
        r"    IORPC rpc = { \1 };", inv - int(interrupt), counts, "rpc_initializers")
    text = replace(text,
        r"#ifdef KERNEL\n    const (\w+)_Msg \* +message = rpc\.message;\n"
        r"    const \1_Msg_Content \* messageContent = rpc\.kernelContent;\n"
        r"#else /\* KERNEL \*/\n    const \1_Msg_With_Content \* message = rpc\.message;\n#endif /\* KERNEL \*/",
        r"    const \1_Msg_With_Content * message = rpc.message;", inv, counts, "typed_packed_message")

    # Bounds are inserted before even generated scalar count initializers, which
    # can read MESSAGE_CONTENT before the original generator's later checks.
    def entry(match):
        name = match[1]
        return ("    if (!mtk_iig_legacy_request(_rpc, sizeof(" + name + "_Msg_With_Content),\n"
                "            __builtin_offsetof(" + name + "_Msg_With_Content, content),\n"
                "            " + name + "_Msg_ObjRefs, " + name + "_ID)) return (kIOReturnIPCError);\n" + match[0])
    text = replace(text, r"^    (\w+)_Invocation rpc = \{ _rpc \};$", entry,
                   inv, counts, "request_entry_bounds")
    text = replace(text,
        r"#if __has_builtin\(__builtin_assume\)\n    __builtin_assume\(reply != NULL\);\n"
        r"#endif /\* __has_builtin\(__builtin_assume\) \*/",
        "    if (!reply || rpc.replySize < sizeof(*reply)) return (kIOReturnIPCError);",
        required, counts, "reply_bounds_before_assumption")
    # Every one of the 85 ordinary generated reply producers explicitly uses
    # this version. CheckForWork's different loop returns a request, not one of
    # these normal replies, and is separately parsed below.
    text = replace(text,
        r"    if \(kIOReturnSuccess == ret\)\n    do \{\n        \{",
        "    if (kIOReturnSuccess == ret)\n    do {\n"
        "        if (rpl->mach.msgh.msgh_id != kIORPCVersion190615Reply) { ret = kIOReturnIPCError; break; };\n"
        "        {", required - int(special), counts, "ordinary_reply_protocol")

    # CheckForWork transports a request-shaped asynchronous message in the
    # reply buffer. The helper's bool chooses the buffer, not a reply version.
    text = replace(text,
        r"#ifdef KERNEL\n            message = rpc\.kernelContent;\n#else /\* KERNEL \*/\n"
        r"            message = IORPCMessageFromMach\(rpc\.reply, false\);\n#endif /\* KERNEL \*/",
        "            message = mtk_iig_legacy_message(rpc, true);\n"
        "            if (!message) return (kIOReturnIPCError);", int(special), counts, "work_reply_bounds")
    text = replace(text,
        r"#ifdef KERNEL\n    replyMessage = rpc\.rpc\.kernelContent;\n#else /\* KERNEL \*/\n"
        r"    replyMessage = IORPCMessageFromMach\(rpc\.rpc\.reply, false\);\n#endif /\* KERNEL \*/",
        "    replyMessage = mtk_iig_legacy_message(rpc.rpc, true);\n"
        "    if (!replyMessage) return (kIOReturnIPCError);", int(special), counts, "work_invoke_reply_bounds")
    # A bounded header with zero objectRefs is valid to the general parser,
    # but CheckForWork's caller subsequently consumes objects[0]. Require the
    # logical reference before either returning or forwarding that message.
    text = replace(text,
        r"            if \(!message\) return \(kIOReturnIPCError\);",
        "            if (!message || message->objectRefs < 1) return (kIOReturnIPCError);",
        int(special), counts, "work_reply_required_object")
    text = replace(text,
        r"    if \(!replyMessage\) return \(kIOReturnIPCError\);",
        "    if (!replyMessage || replyMessage->objectRefs < 1) return (kIOReturnIPCError);",
        int(special), counts, "work_invoke_reply_required_object")
    text = replace(text,
        r"                  rpc\.sendSize  = rpc\.replySize;",
        "                  rpc.message   = rpc.reply;\n                  rpc.sendSize  = rpc.replySize;",
        int(special), counts, "work_forward_reply_as_request")
    text = replace(text,
        r"#ifdef KERNEL\n    rpc\.kernelContent = &msg->content\.__hdr;\n#endif /\* KERNEL \*/",
        "    if (!msg || rpc.replySize < sizeof(*msg)) return (kIOReturnIPCError);",
        int(interrupt), counts, "interrupt_reply_write_bounds")
    if any(marker in text for marker in ("kernelContent", "messageContent", "IORPCMessageFromMach(",
                                          "__builtin_assume(reply != NULL)")):
        raise ValueError("unhandled new ABI/parser shape remains")
    # Only candidates targeting this legacy kernel may include this helper.
    text = '#include "' + HELPER + '"\nstatic_assert(sizeof(IORPC) == 24, "legacy IORPC ABI");\n' + text
    return text, counts


def load_pinned(path, expected):
    data = path.read_bytes()
    if sha(data) != expected:
        raise ValueError("pinned manifest hash mismatch: " + str(path))
    return json.loads(data)


def run(args):
    generated = args.generated.resolve()
    source = generated / "DriverKit"
    profile = json.loads(PROFILE.read_text())
    report = load_pinned(generated / "generation.json", args.generation_sha256)
    inputs = load_pinned(args.inputs / "inputs.json", args.input_sha256)
    if (report.get("status") != "diagnostic-generated-not-compatible" or
            report.get("diagnostic_xcode_major") != 26 or report.get("iig_version") != "DriverKit-440" or
            report.get("inputs_sha256") != args.input_sha256 or report.get("classes") != profile["classes"] or
            report.get("platform") != "iPhoneOS" or inputs.get("classes") != profile["classes"] or
            report.get("iig_codesign", {}).get("verified") is not True or
            report.get("iig_codesign", {}).get("apple_anchor") is not True):
        raise ValueError("not the reviewed complete diagnostic generation")
    expected = profile["files"]
    if {p.name for p in source.iterdir()} != set(expected) or set(report.get("outputs", {})) != set(expected):
        raise ValueError("wrong generated file inventory")
    transformed, changes = {}, {}
    for name, metadata in expected.items():
        path = source / name
        if path.is_symlink() or not path.is_file():
            raise ValueError("nonregular generated input")
        data = path.read_bytes()
        if sha(data) != metadata["sha256"] or sha(data) != report["outputs"][name]:
            raise ValueError("unreviewed/changed generated source: " + name)
        if name.endswith(".iig.cpp"):
            text, changes[name] = transform_impl(data.decode(), metadata)
            data = text.encode()
        transformed[name] = data
    if args.output.exists() or args.output.is_symlink():
        raise ValueError("output must be new")
    if args.helper.is_symlink() or not args.helper.is_file():
        raise ValueError("helper must be a regular reviewed source file")
    helper = args.helper.read_bytes()
    args.output.mkdir()
    (args.output / "DriverKit").mkdir()
    for name, data in transformed.items():
        (args.output / "DriverKit" / name).write_bytes(data)
    (args.output / "DriverKit" / HELPER).write_bytes(helper)
    result = dict(format=1, status="legacy-transform-candidate-not-compatible", replay_eligible=False,
        generation_sha256=args.generation_sha256, inputs_sha256=args.input_sha256,
        profile_sha256=sha(PROFILE.read_bytes()), transform_sha256=sha(Path(__file__).read_bytes()),
        helper_sha256=sha(helper), classes=profile["classes"], operations=changes,
        pristine_outputs=report["outputs"], outputs={k:sha(v) for k,v in transformed.items()},
        requirements=["wire-layout and method-ID comparison", "target compilation and exports",
                      "malformed RPC and dispatch runtime tests", "separate explicit import review"])
    (args.output / "transform.json").write_text(json.dumps(result, indent=2) + "\n")
    print(json.dumps(dict(output=str(args.output), status=result["status"], files=len(transformed))))


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--generated", type=Path, required=True)
    p.add_argument("--generation-sha256", required=True)
    p.add_argument("--inputs", type=Path, required=True)
    p.add_argument("--input-sha256", required=True)
    p.add_argument("--helper", type=Path, required=True)
    p.add_argument("--output", type=Path, required=True)
    try:
        run(p.parse_args())
    except (ValueError, OSError) as error:
        print("ERROR: " + str(error), file=sys.stderr)
        raise SystemExit(1)


if __name__ == "__main__":
    main()
