#!/usr/bin/env python3
"""Fail-closed replay of reviewed Xcode 15 IIG output; never generates RPC code."""
import argparse
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import re
import sys
import tempfile

CLASSES = sorted('IOBufferMemoryDescriptor IODMACommand IODataQueueDispatchSource '
    'IODispatchQueue IODispatchSource IOEventLink IOInterruptDispatchSource '
    'IOMemoryDescriptor IOMemoryMap IOService IOServiceNotificationDispatchSource '
    'IOServiceStateNotificationDispatchSource IOUserClient IOUserServer IOWorkGroup '
    'OSAction OSObject'.split())
EXTRA_INPUTS = {'config/MasterVersion', 'iokit/DriverKit/Makefile', 'makedefs/MakeInc.def',
    'makedefs/MakeInc.cmd', 'bsd/sys/make_posix_availability.sh', 'bsd/sys/make_symbol_aliasing.sh'}
SUPPORT = {'_posix_availability.h', '_symbol_aliasing.h'}
STATUS = 'generated-structurally-verified-not-compiled'
AVAILABILITY_COMMIT = '5d9baee345b3bc72b26c71adc65f94f2d5e9ced2'
AVAILABILITY_SHA256 = '26842f02be5cb75ab02baa6654153ed0b848ff35122a32fea3a02b8472095234'


def sha(data):
    return hashlib.sha256(data).hexdigest()


def checked_file(root, relative):
    """No escaping, symlink aliases, directories, or platform-dependent paths."""
    rel = PurePosixPath(relative)
    if not relative or rel.is_absolute() or '..' in rel.parts or '\\' in relative or str(rel) != relative:
        raise ValueError('invalid relative path: ' + relative)
    p = root
    for part in rel.parts:
        p = p / part
        if p.is_symlink():
            raise ValueError('symlink not allowed: ' + str(p))
    if not p.is_file():
        raise ValueError('missing regular file: ' + str(p))
    return p


def load_json(data):
    def unique(items):
        result = {}
        for k, v in items:
            if k in result:
                raise ValueError('duplicate JSON key: ' + k)
            result[k] = v
        return result
    return json.loads(data, object_pairs_hook=unique)


def read_pinned(root, name, expected):
    if not re.fullmatch('[0-9a-f]{64}', expected or ''):
        raise ValueError('explicit reviewed SHA256 required for ' + name)
    data = checked_file(root, name).read_bytes()
    if sha(data) != expected:
        raise ValueError('pinned manifest changed: ' + name)
    return load_json(data)


def inventory(root):
    names = set(EXTRA_INPUTS)
    for directory in ('iokit', 'osfmk', 'bsd', 'EXTERNAL_HEADERS'):
        for p in (root / directory).rglob('*'):
            if p.suffix in ('.h', '.iig') and (p.is_file() or p.is_symlink()):
                names.add(p.relative_to(root).as_posix())
    return names


def check_inputs(root, bundle, expected_hash):
    m = read_pinned(bundle, 'inputs.json', expected_hash)
    if (m.get('format') != 1 or m.get('classes') != CLASSES or
            m.get('kernel_version') != '22.5.0' or m.get('upstream_tag') != 'xnu-8796.121.2' or
            m.get('platform') != 'iPhoneOS' or m.get('purpose') != 'code-generation-only' or
            m.get('contains_sdk') is not False or m.get('contains_binaries') is not False):
        raise ValueError('incompatible input manifest')
    hashes = m.get('source_sha256')
    if not isinstance(hashes, dict) or set(hashes) != inventory(root):
        raise ValueError('current source input inventory differs')
    source = bundle / 'source'
    actual = {p.relative_to(source).as_posix() for p in source.rglob('*') if p.is_file() or p.is_symlink()}
    if set(hashes) != actual:
        raise ValueError('bundle source inventory differs')
    for name, expected in hashes.items():
        for tree in (root, source):
            if sha(checked_file(tree, name).read_bytes()) != expected:
                raise ValueError('input changed: ' + str(tree / name))
    if checked_file(root, 'config/MasterVersion').read_text().splitlines()[0] != '22.5.0':
        raise ValueError('incompatible kernel version')
    if sorted(p.stem for p in (root / 'iokit/DriverKit').glob('*.iig')) != CLASSES:
        raise ValueError('interface inventory differs')
    if sha(checked_file(bundle, 'workflow.py').read_bytes()) != m.get('workflow_sha256'):
        raise ValueError('producer workflow hash differs')
    dependencies = m.get('dependencies', {})
    actual_deps = {p.relative_to(bundle / 'dependencies').as_posix()
        for p in (bundle / 'dependencies').rglob('*') if p.is_file() or p.is_symlink()}
    if actual_deps != set(dependencies):
        raise ValueError('dependency inventory differs')
    for name, info in dependencies.items():
        if (name != 'AvailabilityVersions/availability.pl' or info.get('commit') != AVAILABILITY_COMMIT or
                info.get('sha256') != AVAILABILITY_SHA256 or
                sha(checked_file(bundle / 'dependencies', name).read_bytes()) != AVAILABILITY_SHA256):
            raise ValueError('unrecognized/changed public source dependency')
    return m


def strip_comments(text):
    return re.sub(r'/\*.*?\*/|//[^\n]*', '', text, flags=re.S)


def check_pair(cls, header, impl, source=b''):
    """Structural rejection only; compilation/RPC behavior are separate acceptance."""
    texts = [data.decode('utf-8') for data in (header, impl)]
    for text in texts:
        if len(text) < 256 or any(marker in text for marker in
                ('iig shim', 'gen-iig-stubs.py', '__iig_stub_', 'kernelContent')):
            raise ValueError('shim/empty/incompatible output: ' + cls)
    h, cpp = map(strip_comments, texts)
    invokes = set(re.findall(r'\b(\w+_Invoke)\s*\(', h))
    if not invokes or 'IORPC' not in cpp:
        raise ValueError('missing generated RPC declarations: ' + cls)
    original = strip_comments(source.decode('utf-8'))
    def defined(method):
        return bool(re.search(r'\b' + re.escape(cls + '::' + method) + r'\s*\([^;{}]*\)\s*\{', cpp, re.S))
    for method in invokes:
        if not defined(method):
            raise ValueError('missing RPC Invoke definition: ' + cls + '::' + method)
        base = method.removesuffix('_Invoke')
        local_pattern = r'\b' + re.escape(base) + r'\s*\([^;{}]*\)\s*LOCAL\s*;'
        local_call = (re.search(local_pattern, original, re.S) and re.search(local_pattern, h, re.S)
            and re.search(r'\b' + re.escape(base + '_Call') + r'\s*\(', h) and defined(base + '_Call'))
        if not defined(base) and not local_call:
            raise ValueError('missing RPC wrapper definition: ' + cls + '::' + base)
    # Legitimate unknown-method dispatch may return kIOReturnUnsupported.
    return sorted(invokes)


def validate(root, inputs, generated, input_hash, generation_hash):
    manifest = check_inputs(root, inputs, input_hash)
    report = read_pinned(generated, 'generation.json', generation_hash)
    if (report.get('format') != 1 or report.get('status') != STATUS or
            report.get('classes') != CLASSES or report.get('code_generation_only') is not True or
            report.get('inputs_sha256') != input_hash or report.get('platform') != 'iPhoneOS' or
            report.get('diagnostic_xcode_major') is not None or
            report.get('dependencies', {}) != manifest.get('dependencies', {}) or
            not re.match(r'^Xcode 15(?:\.|\s|$)', report.get('xcode_version', ''))):
        raise ValueError('generation provenance/version mismatch')
    # Provenance is recorded by the Mac producer, then pinned after trusted transfer.
    # Linux does not claim to independently execute Apple's codesign verifier.
    signature = report.get('iig_codesign', {})
    if signature.get('verified') is not True or signature.get('apple_anchor') is not True:
        raise ValueError('missing Apple codesign verification from Mac producer')
    for name in ('iig_sha256', 'availability_sha256'):
        if not re.fullmatch('[0-9a-f]{64}', report.get(name, '')):
            raise ValueError('missing tool identity: ' + name)
    if manifest.get('dependencies'):
        staged = checked_file(generated, 'support/sdk/usr/local/libexec/availability.pl')
        if sha(staged.read_bytes()) != AVAILABILITY_SHA256 or report['availability_sha256'] != AVAILABILITY_SHA256:
            raise ValueError('staged availability helper differs')
    check_generation_commands(report)
    expected = {c + suffix for c in CLASSES for suffix in ('.h', '.iig.cpp')}
    if set(report.get('outputs', {})) != expected or {p.name for p in (generated / 'DriverKit').iterdir()} != expected:
        raise ValueError('expected exactly 17 generated pairs')
    contents = {}
    for name in expected:
        data = checked_file(generated, 'DriverKit/' + name).read_bytes()
        if sha(data) != report['outputs'][name]:
            raise ValueError('generated output hash mismatch: ' + name)
        contents[name] = data
    if set(report.get('support_sha256', {})) != SUPPORT:
        raise ValueError('support header inventory differs')
    for name in SUPPORT:
        if sha(checked_file(generated, 'support/bsd/sys/' + name).read_bytes()) != report['support_sha256'][name]:
            raise ValueError('support header hash mismatch: ' + name)
    for cls in CLASSES:
        check_pair(cls, contents[cls + '.h'], contents[cls + '.iig.cpp'],
            checked_file(inputs, 'source/iokit/DriverKit/' + cls + '.iig').read_bytes())
    return contents


def parse_invocation(argv):
    if '--' not in argv:
        raise ValueError('IIG compiler argument separator required')
    split = argv.index('--')
    for option in ('--def', '--header', '--impl', '--framework-name'):
        if argv[:split].count(option) != 1:
            raise ValueError('expected exactly one ' + option)
    parser = argparse.ArgumentParser(add_help=False)
    for option in ('def', 'header', 'impl', 'framework-name'):
        parser.add_argument('--' + option, required=True)
    args = parser.parse_args(argv[:split])
    if args.framework_name != 'DriverKit':
        raise ValueError('only DriverKit supported')
    cls = Path(getattr(args, 'def')).stem
    if cls not in CLASSES or Path(getattr(args, 'def')).name != cls + '.iig':
        raise ValueError('unknown interface')
    if Path(args.header).name != cls + '.h' or Path(args.impl).name != cls + '.iig.cpp':
        raise ValueError('header/implementation pair mismatch')
    return args, cls, argv[split + 1:]


def check_flags(flags):
    required = {'-x': 'c++', '-std': 'gnu++1z', '-D__IIG': '1',
        '-DDRIVERKIT_PRIVATE': '1', '-DPRIVATE_WIFI_ONLY': '1'}
    found = {}
    index = 0
    platforms = []
    while index < len(flags):
        flag = flags[index]
        if flag in ('-I', '-isysroot', '-x'):
            if index + 1 >= len(flags):
                raise ValueError('missing compiler argument')
            if flag == '-x':
                if flag in found:
                    raise ValueError('duplicate semantic flag: -x')
                found[flag] = flags[index + 1]
            index += 2
            continue
        if flag.startswith('-I') and len(flag) > 2:
            pass  # Host include roots relocate; the complete source closure is hashed.
        elif flag.startswith('-DXNU_PLATFORM_'):
            platforms.append(flag)
        elif '=' in flag and flag.split('=', 1)[0] in required:
            key, value = flag.split('=', 1)
            if key in found:
                raise ValueError('duplicate semantic flag: ' + key)
            found[key] = value
        else:
            raise ValueError('unreviewed compiler flag: ' + flag)
        index += 1
    if found != required or platforms != ['-DXNU_PLATFORM_iPhoneOS']:
        raise ValueError('compiler semantics differ from generated bundle')


def check_generation_commands(report):
    developer = PurePosixPath(report.get('developer_dir', ''))
    iig = PurePosixPath(report.get('iig_path', ''))
    if not developer.is_absolute() or not iig.is_relative_to(developer):
        raise ValueError('generator is outside recorded Xcode installation')
    commands = report.get('commands', [])
    if len(commands) != 21 or any(not isinstance(c, list) or not c or any(not isinstance(x, str) for x in c) for c in commands):
        raise ValueError('expected two signature, two preparation and 17 IIG commands')
    signature_command = ['/usr/bin/codesign', '--verify', '--strict', '-R=anchor apple', str(iig)]
    if (commands[0] != signature_command or
            report.get('iig_codesign', {}).get('command') != signature_command or
            commands[1] != ['/usr/bin/codesign', '-d', '--verbose=4', str(iig)]):
        raise ValueError('unrecognized generator signature verification')
    commands = commands[2:]
    if (commands[0][0] != '/bin/sh' or len(commands[0]) != 3 or
            not commands[0][1].endswith('/source/bsd/sys/make_posix_availability.sh') or
            not commands[0][2].endswith('/support/bsd/sys/_posix_availability.h') or
            commands[1][0] != '/bin/bash' or len(commands[1]) != 4 or
            not commands[1][1].endswith('/source/bsd/sys/make_symbol_aliasing.sh') or
            commands[1][2] != report.get('alias_sdk') or
            not commands[1][3].endswith('/support/bsd/sys/_symbol_aliasing.h')):
        raise ValueError('unrecognized support header preparation')
    seen = []
    for command in commands[2:]:
        if command[0] != str(iig):
            raise ValueError('generation command uses another tool')
        args, cls, flags = parse_invocation(command[1:])
        check_flags(flags)
        if not getattr(args, 'def').endswith('/source/iokit/DriverKit/' + cls + '.iig'):
            raise ValueError('generation uses unrecorded definition path')
        if flags.count('-isysroot') != 1 or flags[flags.index('-isysroot') + 1] != report.get('sdk'):
            raise ValueError('generation SDK differs')
        seen.append(cls)
    if seen != CLASSES:
        raise ValueError('generation class command inventory differs')


def safe_destination(root, destination):
    p = Path(destination).absolute()
    if '..' in p.parts or not p.is_relative_to(root) or p == root:
        raise ValueError('output outside configured build root: ' + str(p))
    relative = p.relative_to(root)
    parent = root
    for part in relative.parts:
        parent = parent / part
        if parent.is_symlink():
            raise ValueError('output symlink refused: ' + str(parent))
    if not p.parent.is_dir() or (p.exists() and not p.is_file()):
        raise ValueError('output parent missing or destination not a file')
    return p


def replay(argv, config):
    args, cls, flags = parse_invocation(argv)
    check_flags(flags)
    root, inputs, generated, input_hash, generation_hash, output_root = config
    expected_def = root / 'iokit/DriverKit' / (cls + '.iig')
    if Path(getattr(args, 'def')).resolve() != expected_def:
        raise ValueError('definition must be the matching current source file')
    # Header is make's primary target: commit it last.
    destinations = [safe_destination(output_root, args.impl), safe_destination(output_root, args.header)]
    contents = validate(root, inputs, generated, input_hash, generation_hash)
    # Both files are fully verified before either is changed. A crash may leave one
    # replaced; make must rerun this target after a failed invocation.
    for dest in destinations:
        fd, temporary = tempfile.mkstemp(prefix='.' + dest.name + '.', dir=dest.parent)
        try:
            with os.fdopen(fd, 'wb') as stream:
                stream.write(contents[dest.name])
                stream.flush()
                os.fsync(stream.fileno())
            os.chmod(temporary, 0o644)
            os.replace(temporary, dest)
        finally:
            if os.path.exists(temporary):
                os.unlink(temporary)


def config_from_env():
    names = ('MTK_IIG_XNU', 'MTK_IIG_INPUTS', 'MTK_IIG_GENERATED', 'MTK_IIG_INPUT_SHA256', 'MTK_IIG_GENERATION_SHA256')
    if any(not os.environ.get(name) for name in names):
        raise ValueError('required environment: ' + ', '.join(names))
    root, inputs, generated = [Path(os.environ[n]).resolve() for n in names[:3]]
    output = Path(os.environ.get('MTK_IIG_OUTPUT_ROOT', str(root / 'BUILD'))).absolute()
    if output.is_symlink() or not output.is_dir() or output.resolve() == root or root.is_relative_to(output.resolve()):
        raise ValueError('output root must be an existing separate build directory')
    # Never allow replay into a source subtree, other than the conventional BUILD.
    if output.resolve().is_relative_to(root) and not output.resolve().is_relative_to(root / 'BUILD'):
        raise ValueError('source mutation prohibited')
    return root, inputs, generated, os.environ[names[3]], os.environ[names[4]], output.resolve()


def plan(config):
    root, inputs, generated, ih, gh, build = config
    validate(root, inputs, generated, ih, gh)
    artifacts = []
    for p in sorted(build.rglob('*')):
        if p.is_file() and (p.name.startswith('mach.') or p.name in {c + suffix for c in CLASSES for suffix in ('.h', '.iig.cpp')}):
            artifacts.append(dict(path=str(p.relative_to(build)), sha256=sha(p.read_bytes())))
    return dict(format=1, read_only=True, input_manifest_sha256=ih, generation_manifest_sha256=gh,
        build_root=str(build), preserved_inventory=artifacts,
        required_transition='Preserve/rename entire existing BUILD tree; create a fresh BUILD tree before exporthdrs/dependency rebuild with IIG override. Do not reuse old objects or dependency libraries.',
        changes_performed=[], compile_verified=False, export_verified=False, rpc_verified=False)


def main():
    try:
        config = config_from_env()
        if sys.argv[1:] == ['verify']:
            validate(*config[:5])
            print('PASS: pinned inputs, current source, signed-tool provenance and output structure; compilation/RPC remain unverified')
        elif sys.argv[1:] == ['plan']:
            print(json.dumps(plan(config), indent=2))
        else:
            replay(sys.argv[1:], config)
    except (ValueError, OSError, UnicodeError, KeyError, TypeError) as error:
        print('IIG replay rejected: ' + str(error), file=sys.stderr)
        return 1
    return 0


if __name__ == '__main__':
    sys.exit(main())
