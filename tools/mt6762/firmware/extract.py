#!/usr/bin/env python3
"""Read-only, format-aware extraction of this phone's boot v2 and DT tables.

No dependencies beyond Python. Optional --dtc decompiles extracted FDTs.
Only boot.bin/dtbo.bin/vendor_boot.bin are read; calibration/user partitions are not.
"""
import argparse
import hashlib
import json
from pathlib import Path
import struct
import subprocess
import zlib


def take(data, offset, size):
    if offset < 0 or size < 0 or offset + size > len(data):
        raise ValueError(f"invalid range {offset:#x}+{size:#x}/{len(data):#x}")
    return data[offset:offset + size]


def digest(data):
    return hashlib.sha256(data).hexdigest()


def dt_table(data):
    magic, total, header, entry_size, count, entries, page, version = struct.unpack_from('>8I', data)
    if magic != 0xd7b7ab1e or version != 0 or header < 32 or entry_size < 32:
        raise ValueError('Unsupported Android DT table')
    take(data, 0, total)
    result = []
    for i in range(count):
        entry = struct.unpack('>8I', take(data, entries + i * entry_size, 32))
        size, offset, ident, rev, *custom = entry
        blob = take(data[:total], offset, size)
        if struct.unpack_from('>I', blob)[0] != 0xd00dfeed:
            raise ValueError('DT table member is not an FDT')
        fdt_size = struct.unpack_from('>I', blob, 4)[0]
        if fdt_size != size:
            raise ValueError('DT table and FDT sizes disagree')
        result.append((blob, dict(index=i, offset=offset, size=size, id=ident,
                                  rev=rev, custom=custom, sha256=digest(blob))))
    return result


def fdt_properties(blob):
    """Validate FDT structure and return property bytes keyed by absolute path."""
    magic, total, off_struct, off_strings, _, version, _, _, strings_size, struct_size = struct.unpack_from('>10I', blob)
    if magic != 0xd00dfeed or version != 17 or total != len(blob):
        raise ValueError('Unsupported FDT header')
    strings = take(blob, off_strings, strings_size)
    data = take(blob, off_struct, struct_size)
    pos, stack, nodes = 0, [], {}
    while pos < len(data):
        token, = struct.unpack('>I', take(data, pos, 4))
        pos += 4
        if token == 1:
            end = data.index(0, pos)
            stack.append(data[pos:end].decode())
            pos = (end + 4) & ~3
            nodes['/' + '/'.join(stack[1:])] = {}
        elif token == 2:
            stack.pop()
        elif token == 3:
            size, nameoff = struct.unpack('>II', take(data, pos, 8))
            pos += 8
            name = strings[nameoff:strings.index(0, nameoff)].decode()
            nodes['/' + '/'.join(stack[1:])][name] = take(data, pos, size)
            pos = (pos + size + 3) & ~3
        elif token == 4:
            pass
        elif token == 9:
            if stack:
                raise ValueError('Unclosed FDT node')
            return nodes
        else:
            raise ValueError(f'Invalid FDT token {token}')
    raise ValueError('Missing FDT end token')


def display_property(name, value):
    if name in ('model', 'compatible', 'device_type', 'enable-method', 'method', 'bootargs', 'clock-names', 'status'):
        return value.rstrip(b'\0').decode().split('\0')
    if len(value) % 4 == 0:
        return list(struct.unpack('>' + 'I' * (len(value) // 4), value))
    return {'hex': value.hex()}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--dump', type=Path, required=True)
    parser.add_argument('--out', type=Path, required=True)
    parser.add_argument('--dtc', type=Path)
    args = parser.parse_args()
    if args.out.resolve() == args.dump.resolve() or args.dump.resolve() in args.out.resolve().parents:
        raise ValueError('Output must be outside the original dump')
    args.out.mkdir(parents=True, exist_ok=True)
    report = {'evidence_type': 'static-format-parsing', 'inputs': {}, 'outputs': {}, 'limitations': [
        'No hardware execution; bootloader-mutated live DT and actual installed RAM remain unknown.',
        'DT overlay contains reference display/touch properties inconsistent with compiled kernel config.',
        'No REA Evidence ID: REA firmware tool unavailable because REA_BINWALK_COMMAND is unset; this is an independent parser.']}

    def read(name):
        data = (args.dump / name).read_bytes()
        report['inputs'][name] = {'size': len(data), 'sha256': digest(data)}
        return data

    def write(name, data):
        (args.out / name).write_bytes(data)
        report['outputs'][name] = {'size': len(data), 'sha256': digest(data)}

    data = read('boot.bin')
    if data[:8] != b'ANDROID!':
        raise ValueError('Not an Android boot image')
    keys = ['kernel_size', 'kernel_addr', 'ramdisk_size', 'ramdisk_addr', 'second_size',
            'second_addr', 'tags_addr', 'page_size', 'header_version', 'os_version_encoded']
    header = dict(zip(keys, struct.unpack_from('<10I', data, 8)))
    if header['header_version'] != 2:
        raise ValueError('Only boot header v2 supported')
    rec_size, rec_offset, hdr_size, dtb_size, dtb_addr = struct.unpack_from('<IQIIQ', data, 1632)
    header.update(recovery_dtbo_size=rec_size, recovery_dtbo_offset=rec_offset,
                  header_size=hdr_size, dtb_size=dtb_size, dtb_addr=dtb_addr)
    header['cmdline'] = (data[64:576].split(b'\0')[0] + data[608:1632].split(b'\0')[0]).decode()
    page = header['page_size']
    if page < hdr_size or page & (page - 1):
        raise ValueError('Invalid boot image page size')
    align = lambda size: (size + page - 1) & ~(page - 1)
    offset = page
    sections = {}
    for name in ('kernel', 'ramdisk', 'second'):
        size = header[name + '_size']
        sections[name] = {'offset': offset, 'size': size}
        if size:
            write(name + '.compressed' if name == 'kernel' else name, take(data, offset, size))
        offset += align(size)
    offset += align(rec_size)
    sections['dtb'] = {'offset': offset, 'size': dtb_size}
    report['boot_header'] = header
    report['boot_sections'] = sections
    compressed = take(data, sections['kernel']['offset'], header['kernel_size'])
    decoder = zlib.decompressobj(31)
    kernel = decoder.decompress(compressed) + decoder.flush()
    if not decoder.eof or decoder.unused_data:
        raise ValueError('Unexpected kernel gzip layout')
    if kernel[56:60] != b'ARMd':
        raise ValueError('Not an AArch64 Image')
    write('Image', kernel)
    text_offset, image_size, flags = struct.unpack_from('<3Q', kernel, 8)
    banner = kernel.index(b'Linux version ')
    report['linux_image'] = dict(text_offset=text_offset, image_size=image_size, flags=flags,
                                banner=kernel[banner:kernel.index(0, banner)].decode())
    config_start = kernel.find(b'IKCFG_ST')
    if config_start >= 0:
        config_end = kernel.index(b'IKCFG_ED', config_start)
        config = zlib.decompress(kernel[config_start + 8:config_end], 31)
        write('stock.config', config)
        report['ikconfig'] = dict(start=config_start, end=config_end)
    for table_name, table in [('boot.bin', take(data, offset, dtb_size)), ('dtbo.bin', read('dtbo.bin'))]:
        members = dt_table(table)
        report[table_name + '_dt_table'] = [info for _, info in members]
        for blob, info in members:
            suffix = '' if len(members) == 1 else f'.{info["index"]}'
            name = table_name + suffix + '.dtb'
            write(name, blob)
            nodes = fdt_properties(blob)
            if table_name == 'boot.bin':
                selected = {path: {key: display_property(key, value) for key, value in props.items()}
                            for path, props in nodes.items()
                            if path in ('/', '/chosen', '/memory', '/timer', '/psci')
                            or path.startswith(('/cpus/cpu@', '/serial@', '/interrupt-controller@'))}
                report['boot_dt_selected_nodes'] = selected
            if args.dtc:
                dts_name = ('boot' if table_name == 'boot.bin' else 'overlay') + suffix + '.dts'
                result = subprocess.run([str(args.dtc), '-I', 'dtb', '-O', 'dts', '-o', str(args.out / dts_name), str(args.out / name)], capture_output=True, check=True)
                write(dts_name + '.warnings.log', result.stderr)
    vendor = read('vendor_boot.bin')
    report['vendor_boot_all_zero'] = not any(vendor)
    (args.out / 'evidence.json').write_text(json.dumps(report, indent=2) + '\n')
    print(json.dumps({'boot': header, 'linux': report['linux_image'], 'evidence': str(args.out / 'evidence.json')}, indent=2))


if __name__ == '__main__':
    main()
