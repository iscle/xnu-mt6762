#!/usr/bin/env python3
"""Read-only bounded Mach-O import audit. Writes metadata, never binary contents.

Thin little-endian Mach-O64 is decoded independently of llvm-nm. Other image
formats and embedded kernel collections are explicit coverage gaps, not no-hit
results. Exact ABI names are matched without demangling or substring matching.
"""
import argparse
from collections import Counter
import hashlib
import json
import os
from pathlib import Path
import plistlib
import struct
import subprocess


def sha(data):
    return hashlib.sha256(data).hexdigest()


def bounded(data, offset, size):
    if offset < 0 or size < 0 or offset > len(data) or size > len(data)-offset:
        raise ValueError('range outside input')
    return data[offset:offset+size]


def cstring(data, offset):
    if not 0 <= offset < len(data):
        raise ValueError('string offset outside input')
    end = data.find(b'\0', offset)
    if end < 0:
        raise ValueError('unterminated string')
    return data[offset:end].decode('utf-8', errors='strict'), end+1


def leb(data, offset, signed=False):
    value = 0
    for shift in range(0,70,7):
        b = bounded(data,offset,1)[0]
        offset += 1
        value |= (b & 127) << shift
        if not b & 128:
            if signed and b & 64:
                value -= 1 << (shift+7)
            return value, offset
    raise ValueError('oversized LEB128')


def bind_symbols(data):
    """Collect names only when a bind opcode actually uses the selected symbol."""
    offset, symbol, result = 0, None, set()
    while offset < len(data):
        b=data[offset]; offset+=1
        op, imm = b & 0xf0, b & 15
        if op == 0:
            symbol=None  # lazy bind streams can contain several DONE blocks
        elif op in (0x10,0x30,0x50):
            pass
        elif op in (0x20,0x70,0x80):
            _,offset=leb(data,offset)
        elif op == 0x60:
            _,offset=leb(data,offset,True)
        elif op == 0x40:
            symbol,offset=cstring(data,offset)
        elif op in (0x90,0xa0,0xb0,0xc0):
            if symbol is None:
                raise ValueError('bind without symbol')
            count=1
            if op == 0xa0:
                _,offset=leb(data,offset)
            elif op == 0xc0:
                count,offset=leb(data,offset)
                _,offset=leb(data,offset)
            if count:
                result.add(symbol)
        else:
            raise ValueError(f'unsupported bind opcode {b:#x}')
    return result


def parse_macho(data):
    if data[:4] != b'\xcf\xfa\xed\xfe':
        raise ValueError('unsupported Mach-O format; thin little-endian 64-bit required')
    _,cpu,sub,filetype,ncmds,cmdbytes,flags,_=struct.unpack('<8I',bounded(data,0,32))
    commands=bounded(data,32,cmdbytes)
    pos=0; imports={}; info=[]; gaps=[]; symtab_present=False
    def add(names, source):
        for name in names:
            imports.setdefault(name,set()).add(source)
    for _ in range(ncmds):
        cmd,size=struct.unpack('<II',bounded(commands,pos,8))
        if size < 8 or size % 4:
            raise ValueError('invalid load-command size')
        payload=bounded(commands,pos,size);pos+=size
        if cmd == 2:
            symtab_present=True
            so,n,stro,strsize=struct.unpack('<4I',bounded(payload,8,16))
            symbols=bounded(data,so,n*16);strings=bounded(data,stro,strsize)
            names=[]
            for off in range(0,len(symbols),16):
                idx,typ,sect,desc,value=struct.unpack_from('<IBBHQ',symbols,off)
                if not typ & 0xe0 and typ & 0x0e == 0 and typ & 1:
                    name,_=cstring(strings,idx);names.append(name)
            add(names,'LC_SYMTAB.N_UNDF')
            info.append(dict(command='LC_SYMTAB',symbol_count=n,undefined_count=len(names)))
        elif cmd in (0x22,0x80000022):
            fields=struct.unpack('<10I',bounded(payload,8,40))
            for index,label in ((2,'bind'),(4,'weak_bind'),(6,'lazy_bind')):
                off,length=fields[index:index+2]
                if length:
                    try:
                        names=bind_symbols(bounded(data,off,length));add(names,'LC_DYLD_INFO.'+label)
                        info.append(dict(command='LC_DYLD_INFO.'+label,import_count=len(names)))
                    except ValueError as error:
                        gaps.append(str(error))
        elif cmd == 0x80000034:
            off,length=struct.unpack('<II',bounded(payload,8,8));blob=bounded(data,off,length)
            version,starts,io,ss,count,fmt,sfmt=struct.unpack('<7I',bounded(blob,0,28))
            if version != 0 or sfmt != 0 or fmt not in (1,2,3):
                gaps.append(f'unsupported chained fixups version/import/symbol format {version}/{fmt}/{sfmt}')
                continue
            stride={1:4,2:8,3:16}[fmt];table=bounded(blob,io,count*stride);strings=bounded(blob,ss,len(blob)-ss)
            names=[]
            for off in range(0,len(table),stride):
                if fmt == 3:
                    raw=struct.unpack_from('<Q',table,off)[0];nameoff=raw>>32
                else:
                    raw=struct.unpack_from('<I',table,off)[0];nameoff=raw>>9
                name,_=cstring(strings,nameoff);names.append(name)
            add(names,'LC_DYLD_CHAINED_FIXUPS.import_table')
            info.append(dict(command='LC_DYLD_CHAINED_FIXUPS',import_count=count,imports_format=fmt))
        elif cmd == 0x80000035:
            gaps.append('LC_FILESET_ENTRY embedded image not recursively audited')
    if pos != len(commands):
        raise ValueError('load-command byte count mismatch')
    if not symtab_present:
        gaps.append('no LC_SYMTAB; only represented bind/import tables covered')
    return dict(cpu_type=hex(cpu),cpu_subtype=hex(sub),filetype=filetype,
                load_commands=ncmds,import_tables=info,coverage_gaps=gaps), imports


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--exports',type=Path,required=True)
    p.add_argument('--extensions',type=Path,required=True)
    p.add_argument('--llvm-nm',type=Path,required=True)
    p.add_argument('--search-root',type=Path,action='append',default=[])
    p.add_argument('--kernelcache',type=Path,action='append',default=[])
    p.add_argument('--output',type=Path,required=True)
    args=p.parse_args()
    exports=json.loads(args.exports.read_text())
    targets={x['mangled']:x for x in exports['missing_exports']}
    if len(targets) != exports['missing_count']:
        raise ValueError('duplicate or inconsistent target inventory')
    inventory=[];bundles=[];native=[];hits=[];missing=[]
    paths=sorted(args.extensions.rglob('*'))
    for path in paths:
        relative=str(path.relative_to(args.extensions))
        if path.is_symlink():
            inventory.append(dict(path=relative,kind='symlink',target=os.readlink(path)))
            continue
        if not path.is_file():
            continue
        data=path.read_bytes()
        inventory.append(dict(path=relative,kind='file',bytes=len(data),sha256=sha(data)))
        if path.name == 'Info.plist':
            try:
                plist=plistlib.loads(data);exe=plist.get('CFBundleExecutable')
                row=dict(path=relative,bundle_id=plist.get('CFBundleIdentifier'),executable=exe,
                         dependencies=plist.get('OSBundleLibraries',{}))
                if exe:
                    row['standalone_executable_present']=(path.parent/exe).is_file()
                    if not row['standalone_executable_present']:
                        missing.append(str((path.parent/exe).relative_to(args.extensions)))
                bundles.append(row)
            except (ValueError,plistlib.InvalidFileException) as error:
                bundles.append(dict(path=relative,error=str(error)))
        if data[:4] in (b'\xcf\xfa\xed\xfe',b'\xce\xfa\xed\xfe',b'\xfe\xed\xfa\xcf',b'\xca\xfe\xba\xbe',b'\xca\xfe\xba\xbf'):
            native.append((relative,path,data))
    for path in args.kernelcache:
        data=path.read_bytes();name='kernelcache:'+path.name
        inventory.append(dict(path=name,kind='explicit_kernelcache',bytes=len(data),sha256=sha(data)))
        native.append((name,path,data))
    images=[]
    for name,path,data in native:
        row=dict(path=name,sha256=sha(data))
        try:
            meta,imports=parse_macho(data);row.update(meta)
            row['unique_imports']=len(imports)
            matched=sorted(set(imports)&targets.keys())
            row['matched_imports']={symbol:sorted(imports[symbol]) for symbol in matched}
            hits.extend(dict(path=name,symbol=symbol,sources=sorted(imports[symbol])) for symbol in matched)
            proc=subprocess.run([str(args.llvm_nm),'--undefined-only','--just-symbol-name',str(path)],capture_output=True,text=True,timeout=30)
            nm_names={line.strip() for line in proc.stdout.splitlines() if line.strip()}
            row['llvm_nm']=dict(returncode=proc.returncode,stderr=proc.stderr.strip(),
                                undefined_count=len(nm_names),matched_targets=sorted(nm_names&targets.keys()),
                                stdout_sha256=sha(proc.stdout.encode()))
            sym_names={n for n,sources in imports.items() if 'LC_SYMTAB.N_UNDF' in sources}
            row['symtab_nm_agree']=proc.returncode==0 and sym_names==nm_names
            if not row['symtab_nm_agree']:
                row['coverage_gaps'].append('LLVM nm and independent undefined-symbol inventories differ')
        except (ValueError,struct.error,subprocess.TimeoutExpired) as error:
            row['coverage_gaps']=[str(error)]
        images.append(row)
    searches=[]
    for root in args.search_root:
        proc=subprocess.run(['rg','--files','--hidden','--no-ignore',str(root),'-g','*kernelcache*','-g','*prelinked*','-g','*.kc','-g','*.ipsw'],capture_output=True,text=True,timeout=60)
        candidates=sorted(str(Path(line).relative_to(root)) for line in proc.stdout.splitlines())
        searches.append(dict(root=str(root),command='rg --files --hidden --no-ignore ROOT -g *kernelcache* -g *prelinked* -g *.kc -g *.ipsw',returncode=proc.returncode,stderr=proc.stderr.strip(),candidates=candidates,
                             limitation='Filename inventory; renamed, encrypted or separately mounted caches are not excluded.'))
    result=dict(target_audit_sha256=sha(args.exports.read_bytes()),target_count=len(targets),targets=list(targets.values()),
                llvm_nm=dict(path=str(args.llvm_nm),sha256=sha(args.llvm_nm.read_bytes()),version=subprocess.check_output([str(args.llvm_nm),'--version'],text=True).strip()),
                scope=dict(extensions=str(args.extensions),kernelcache_search=searches,explicit_kernelcache_count=len(args.kernelcache)),
                inventory=inventory,bundles=bundles,missing_standalone_executables=missing,images=images,actual_import_hits=hits,
                counts=dict(files=len(inventory),mach_o_images=len(images),filetypes=dict(Counter(str(x.get('filetype','unknown')) for x in images)),hits=len(hits)),
                limitations=['No live or donor kernelcache completeness claim.', 'Missing executable may be resident in a dyld shared cache; shared caches are outside this directory audit.', 'Chained import-table presence is a declared dependency; dynamic reachability is not proved.', 'String-only matches, object selectors and indirect runtime symbol construction are not treated as static imports.', 'No exports, kernel inputs or proprietary binaries changed or published.'])
    args.output.parent.mkdir(parents=True,exist_ok=True)
    args.output.write_text(json.dumps(result,indent=2)+'\n')
    print(json.dumps(result['counts']))

if __name__=='__main__':
    main()
