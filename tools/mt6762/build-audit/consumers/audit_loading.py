#!/usr/bin/env python3
"""Bounded source and frozen-kernel loading-path evidence; no kernel changes."""
import argparse
import hashlib
import json
from pathlib import Path
import re
import struct
import subprocess


def sha(data):return hashlib.sha256(data).hexdigest()


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--xnu',type=Path,required=True)
    p.add_argument('--loader',type=Path,required=True)
    p.add_argument('--kernel',type=Path,required=True)
    p.add_argument('--exports',type=Path,required=True)
    p.add_argument('--llvm-nm',type=Path,required=True)
    p.add_argument('--output',type=Path,required=True)
    a=p.parse_args();e=json.loads(a.exports.read_text());data=a.kernel.read_bytes()
    if sha(data)!=e['kernel_sha256']:raise ValueError('kernel differs from requested export audit')
    if data[:4]!=b'\xcf\xfa\xed\xfe':raise ValueError('expected thin Mach-O64')
    segments=[];fileset=False;o=32
    for _ in range(struct.unpack_from('<I',data,16)[0]):
        c,s=struct.unpack_from('<II',data,o)
        if s<8 or o+s>len(data):raise ValueError('bad load-command range')
        if c==0x19:
            name=data[o+8:o+24].split(b'\0')[0].decode()
            va,vs,fo,fs=struct.unpack_from('<4Q',data,o+24)
            if name.startswith('__PRELINK'):
                segments.append(dict(name=name,vmsize=vs,filesize=fs))
        if c==0x80000035:fileset=True
        o+=s
    paths=['libsa/bootstrap.cpp','libkern/c++/OSKext.cpp','iokit/Kernel/IOCatalogue.cpp',
           'config/MASTER','config/Private.arm64.exports']
    patterns=['readPrelinkedExtensions','readBooterExtensions','BOOTER_KEXT_PREFIX',
              'CONFIG_KXLD','Refusing to link non-prelinked kext','loadKernelComponentKexts',
              'loadKernelExternalComponents','readBuiltinPersonalities']
    sources=[]
    for path in paths:
        b=(a.xnu/path).read_bytes();lines=b.decode().splitlines()
        sources.append(dict(path=path,sha256=sha(b),selected_lines=[dict(line=i,text=line.strip()) for i,line in enumerate(lines,1) if any(pat in line for pat in patterns)]))
    loader=a.loader.read_bytes();sources.append(dict(path='boot/prepare.py',sha256=sha(loader),selected_lines=[dict(line=i,text=line.strip()) for i,line in enumerate(loader.decode().splitlines(),1) if any(pat in line for pat in ('memory-map','RAMDisk','parse_macho(data)','m[\'segments\']'))]))
    proc=subprocess.run([str(a.llvm_nm),'--just-symbol-name',str(a.kernel)],capture_output=True,text=True,check=True)
    symbols=set(proc.stdout.splitlines());kxld=sorted(s for s in symbols if 'kxld' in s.lower())
    # Exact C identifier searches avoid counting pmap_iommu_disconnect tests.
    c_names=[row['mangled'][1:] for row in e['missing_exports'] if not row['mangled'].startswith('__Z')]
    pattern=r'\b(?:'+ '|'.join(map(re.escape,c_names+['IOUnifiedAddressTranslator']))+r')\b'
    roots=[a.xnu/p for p in ('bsd','osfmk','iokit','libkern','libsa','pexpert')]
    search=subprocess.run(['rg','-n',pattern,*map(str,roots),'-g','*.c','-g','*.cpp','-g','*.h','-g','*.s'],capture_output=True,text=True)
    if search.returncode not in (0,1):raise ValueError(search.stderr)
    result=dict(export_audit_sha256=sha(a.exports.read_bytes()),kernel_sha256=sha(data),
                kernel_filetype=struct.unpack_from('<I',data,12)[0],prelink_segments=segments,has_fileset_entries=fileset,
                contains_no_kxld_refusal_diagnostic=b'Refusing to link non-prelinked kext:' in data,
                nm_kxld_names=kxld,nm_stdout_sha256=sha(proc.stdout.encode()),
                static_source_search=dict(pattern=pattern,roots=[str(x.relative_to(a.xnu)) for x in roots],suffixes=['.c','.cpp','.h','.s'],matches=search.stdout.replace(str(a.xnu)+'/', '').splitlines(),scope='Exact C identifiers and UAT class in selected implementation roots; export files and generated BUILD intentionally separate.'),
                sources=sources,
                interpretation='Frozen linked image has empty prelink segments, no fileset entries or kxld names; current loader supplies one linked Mach-O and RAMDisk memory-map entries. Source retains prelinked/booter-kext machinery, but the current producer does not supply Driver- kext entries. This does not prove absence of future/external consumers or disable all OSKext machinery.',
                changes_made_to_kernel_or_exports=False)
    a.output.write_text(json.dumps(result,indent=2)+'\n')
    print('Frozen build verified; prelink segments, source loading paths and exact identifier search recorded.')


if __name__=='__main__':main()
