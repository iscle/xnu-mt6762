#!/usr/bin/env python3
"""Explicit experimental IIG440 legacy candidate replay; never normal admission."""
import json
import os
from pathlib import Path
import re
import sys
import tempfile
import legacy_transform
import replay


def config_from_env():
    base = replay.config_from_env()
    candidate = os.environ.get('MTK_IIG_CANDIDATE')
    pin = os.environ.get('MTK_IIG_CANDIDATE_SHA256')
    if not candidate or not pin:
        raise ValueError('explicit MTK_IIG_CANDIDATE and MTK_IIG_CANDIDATE_SHA256 required')
    return base, Path(candidate).resolve(), pin


def validate(config):
    base, candidate, pin = config
    root, inputs, generated, ih, gh, output_root = base
    source = replay.check_inputs(root, inputs, ih)
    report = replay.read_pinned(generated, 'generation.json', gh)
    transformed = replay.read_pinned(candidate, 'transform.json', pin)
    if (report.get('format') != 1 or report.get('status') != 'diagnostic-generated-not-compatible' or
            report.get('diagnostic_xcode_major') != 26 or report.get('iig_version') != 'DriverKit-440' or
            not re.match(r'^Xcode 26(?:\.|\s|$)', report.get('xcode_version', '')) or
            report.get('code_generation_only') is not True or report.get('inputs_sha256') != ih or
            report.get('classes') != replay.CLASSES or report.get('platform') != 'iPhoneOS' or
            report.get('dependencies', {}) != source.get('dependencies', {}) or
            report.get('iig_codesign', {}).get('verified') is not True or
            report.get('iig_codesign', {}).get('apple_anchor') is not True):
        raise ValueError('not the reviewed complete signed-tool diagnostic generation')
    replay.check_generation_commands(report)
    for name in ('iig_sha256', 'availability_sha256'):
        if not re.fullmatch('[0-9a-f]{64}', report.get(name, '')):
            raise ValueError('missing generator identity')
    if source.get('dependencies'):
        helper = replay.checked_file(generated, 'support/sdk/usr/local/libexec/availability.pl')
        if replay.sha(helper.read_bytes()) != replay.AVAILABILITY_SHA256 or report['availability_sha256'] != replay.AVAILABILITY_SHA256:
            raise ValueError('availability source changed')
    if set(report.get('support_sha256', {})) != replay.SUPPORT:
        raise ValueError('support header inventory differs')
    for name, expected in report['support_sha256'].items():
        if replay.sha(replay.checked_file(generated, 'support/bsd/sys/' + name).read_bytes()) != expected:
            raise ValueError('support header changed')
    if (transformed.get('format') != 1 or transformed.get('status') != 'legacy-transform-candidate-not-compatible' or
            transformed.get('replay_eligible') is not False or transformed.get('generation_sha256') != gh or
            transformed.get('inputs_sha256') != ih or transformed.get('classes') != replay.CLASSES or
            transformed.get('pristine_outputs') != report.get('outputs')):
        raise ValueError('candidate provenance mismatch')
    directory = Path(__file__).resolve().parent
    for field, name in [('transform_sha256', 'legacy_transform.py'), ('profile_sha256', 'legacy440_profile.json'),
                        ('helper_sha256', 'MTKIIGLegacy.h')]:
        if replay.sha(replay.checked_file(directory, name).read_bytes()) != transformed.get(field):
            raise ValueError('candidate source changed: ' + name)
    profile = replay.load_json((directory / 'legacy440_profile.json').read_bytes())
    expected_names = {c + suffix for c in replay.CLASSES for suffix in ('.h', '.iig.cpp')}
    if (set(report.get('outputs', {})) != expected_names or set(transformed.get('outputs', {})) != expected_names or
            set(profile.get('files', {})) != expected_names or
            {p.name for p in (generated / 'DriverKit').iterdir()} != expected_names or
            {p.name for p in (candidate / 'DriverKit').iterdir()} != expected_names | {'MTKIIGLegacy.h'}):
        raise ValueError('candidate/pristine inventory differs')
    contents, operations = {}, {}
    for name in sorted(expected_names):
        pristine = replay.checked_file(generated, 'DriverKit/' + name).read_bytes()
        digest = replay.sha(pristine)
        if digest != report['outputs'][name] or digest != profile['files'][name]['sha256']:
            raise ValueError('pristine output changed: ' + name)
        expected = pristine
        if name.endswith('.iig.cpp'):
            text, operations[name] = legacy_transform.transform_impl(pristine.decode(), profile['files'][name])
            expected = text.encode()
        data = replay.checked_file(candidate, 'DriverKit/' + name).read_bytes()
        if data != expected or replay.sha(data) != transformed['outputs'][name]:
            raise ValueError('candidate is not exact reviewed transform: ' + name)
        contents[name] = data
    if operations != transformed.get('operations'):
        raise ValueError('transform operation inventory differs')
    helper = replay.checked_file(candidate, 'DriverKit/MTKIIGLegacy.h').read_bytes()
    if replay.sha(helper) != transformed['helper_sha256']:
        raise ValueError('candidate compatibility helper changed')
    contents['MTKIIGLegacy.h'] = helper
    for cls in replay.CLASSES:
        replay.check_pair(cls, contents[cls + '.h'], contents[cls + '.iig.cpp'],
            replay.checked_file(inputs, 'source/iokit/DriverKit/' + cls + '.iig').read_bytes())
    return contents


def run_copy(argv, config):
    args, cls, flags = replay.parse_invocation(argv)
    replay.check_flags(flags)
    root, inputs, generated, ih, gh, output = config[0]
    if Path(getattr(args, 'def')).resolve() != root / 'iokit/DriverKit' / (cls + '.iig'):
        raise ValueError('definition must match current source interface')
    header = replay.safe_destination(output, args.header)
    impl = replay.safe_destination(output, args.impl)
    helper = replay.safe_destination(output, impl.parent / 'MTKIIGLegacy.h')
    contents = validate(config)
    # All validation precedes mutations. Header (make primary target) goes last.
    # Parallel invocations install identical pinned helper bytes atomically.
    for destination in (helper, impl, header):
        fd, temporary = tempfile.mkstemp(prefix='.' + destination.name + '.', dir=destination.parent)
        try:
            with os.fdopen(fd, 'wb') as stream:
                stream.write(contents[destination.name])
                stream.flush()
                os.fsync(stream.fileno())
            os.chmod(temporary, 0o644)
            os.replace(temporary, destination)
        finally:
            if os.path.exists(temporary):
                os.unlink(temporary)


def main():
    try:
        config = config_from_env()
        if sys.argv[1:] == ['verify']:
            contents = validate(config)
            print(json.dumps(dict(status='experimental-candidate-inputs-verified', files=len(contents),
                normal_replay_eligible=False, compile_verified=False, rpc_verified=False,
                candidate_sha256=config[2], generation_sha256=config[0][4], inputs_sha256=config[0][3])))
        else:
            run_copy(sys.argv[1:], config)
    except (ValueError, OSError, UnicodeError, KeyError, TypeError) as error:
        print('Experimental IIG replay rejected: ' + str(error), file=sys.stderr)
        return 1
    return 0


if __name__ == '__main__':
    sys.exit(main())
