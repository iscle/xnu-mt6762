#!/usr/bin/env python3
"""Bounded live-topology admission; synthetic fixtures, no hardware operations."""
import ctypes as C
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
HERE=Path(__file__).resolve().parent
sys.path.insert(0,str(HERE.parent))
from test_fdt_handoff import node,fdt,U32,U64

class Topology(C.Structure):
    _fields_=[('count',C.c_uint32),('mpidr',C.c_uint32*8),('smc',C.c_uint32),('observed_count',C.c_uint32)]
def cpu(reg, extra=(), replace=None):
    props={'compatible':b'arm,cortex-a53\0','device_type':b'cpu\0','reg':U32(reg),'enable-method':b'psci\0'}
    props.update(replace or {})
    return node('cpu@%03x'%reg,list(props.items())+list(extra))
def tree(cpus=None,cpu_props=None,psci_props=None,extra=(),compatible=b'mediatek,MT6765\0'):
    if cpus is None:cpus=[cpu(x) for x in (0,1,2,3,0x100,0x101,0x102,0x103)]
    if cpu_props is None:cpu_props=[('#address-cells',U32(1)),('#size-cells',U32(0))]
    if psci_props is None:psci_props=[('compatible',b'arm,psci-1.0\0'),('method',b'smc\0')]
    return node('',[('#address-cells',U32(2)),('#size-cells',U32(2)),('compatible',compatible)],[
        node('memory@40000000',[('device_type',b'memory\0'),('reg',U64(0x40000000)+U64(0xc0000000))]),
        node('cpus',cpu_props,cpus),node('psci',psci_props)]+list(extra))
class Tests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp=tempfile.TemporaryDirectory();cls.addClassCleanup(cls.tmp.cleanup)
        so=Path(cls.tmp.name)/'psci.so'
        subprocess.run(['cc','-std=c11','-O2','-Wall','-Wextra','-Werror','-ffreestanding','-shared','-fPIC',str(HERE/'psci_fdt.c'),str(HERE.parent/'fdt_handoff.c'),'-o',str(so)],check=True)
        cls.lib=C.CDLL(str(so));cls.lib.mtk_psci_fdt_topology.argtypes=[C.c_void_p,C.c_size_t,C.c_uint64,C.c_uint,C.POINTER(Topology)]
    def parse(self,blob=None,requested=2,mpidr=0x80000000):
        if blob is None:blob=fdt(tree())
        buf=C.create_string_buffer(blob);out=Topology();C.memset(C.byref(out),0xa5,C.sizeof(out))
        rc=self.lib.mtk_psci_fdt_topology(buf,len(blob),mpidr,requested,C.byref(out))
        if rc:self.assertEqual(bytes(out),bytes(C.sizeof(out)))
        return rc,out
    def reject(self,**kw):self.assertNotEqual(self.parse(**kw)[0],0)
    def test_two_four_eight_and_node_order(self):
        regs=[0,1,2,3,0x100,0x101,0x102,0x103]
        for requested in (2,4,8):
            for order in (regs,list(reversed(regs))):
                rc,t=self.parse(fdt(tree(cpus=[cpu(x) for x in order])),requested)
                self.assertEqual(rc,0);self.assertEqual(t.count,requested);self.assertEqual(t.observed_count,8);self.assertEqual(t.smc,1)
                self.assertEqual(list(t.mpidr),regs[:requested]+[0]*(8-requested))
    def test_architectural_mpidr_flags(self):
        for value in (0,0x80000000,0x81000000,0x01000000):self.assertEqual(self.parse(mpidr=value)[0],0)
        for value in (1,0x100,0x10000,0x100000000,0x40000000,1<<63):self.reject(mpidr=value)
    def test_missing_duplicate_extra_cpu(self):
        regs=[0,1,2,3,0x100,0x101,0x102,0x103]
        for nodes in ([cpu(x) for x in regs[:-1]],[cpu(x) for x in regs]+[cpu(0)],
            [cpu(x) for x in regs]+[node('mystery',[('device_type',b'cpu\0')])]):self.reject(blob=fdt(tree(cpus=nodes)))
    def test_cpu_contract(self):
        for change in ({'status':b'disabled\0'},{'compatible':b'arm,cortex-a55\0'},{'device_type':b'other\0'},
            {'reg':U32(4)},{'reg':U64(0)},{'enable-method':b'spin-table\0'},{'enable-method':b'psci'}):
            nodes=[cpu(0,replace=change)]+[cpu(x) for x in (1,2,3,0x100,0x101,0x102,0x103)]
            self.reject(blob=fdt(tree(cpus=nodes)))
        nodes=[cpu(0,extra=[('reg',U32(0))])]+[cpu(x) for x in (1,2,3,0x100,0x101,0x102,0x103)]
        self.reject(blob=fdt(tree(cpus=nodes)))
    def test_cells_and_psci(self):
        for cells in ((2,0),(1,1)):
            self.reject(blob=fdt(tree(cpu_props=[('#address-cells',U32(cells[0])),('#size-cells',U32(cells[1]))])))
        for props in ([('compatible',b'arm,psci-1.0\0'),('method',b'hvc\0')],
            [('compatible',b'arm,psci-1.0\0')],[('compatible',b'arm,psci-0.2\0'),('method',b'smc\0')],
            [('compatible',b'arm,psci-1.0\0'),('method',b'smc\0'),('method',b'smc\0')]):
            self.reject(blob=fdt(tree(psci_props=props)))
        self.reject(blob=fdt(tree(extra=[node('psci')])));self.reject(blob=fdt(tree(extra=[node('cpus')])))
    def test_board_and_count(self):
        self.reject(blob=fdt(tree(compatible=b'mediatek,other\0')))
        for requested in (0,1,3,5,7,9,0xffffffff):self.reject(requested=requested)
        self.assertEqual(self.parse(fdt(tree(compatible=b'mediatek,MT6762\0')))[0],0)
    def test_truncation_and_corrupt_header(self):
        b=fdt(tree())
        for n in (0,4,39,40,len(b)-1):self.reject(blob=b[:n])
        self.reject(blob=b'BAD!'+b[4:])
    @unittest.skipUnless(os.environ.get('MTK_PSCI_TEST_DTB'),'optional private captured DTB')
    def test_actual_capture(self):
        b=Path(os.environ['MTK_PSCI_TEST_DTB']).read_bytes()
        for requested in (2,4,8):self.assertEqual(self.parse(b,requested)[0],0)
if __name__=='__main__':unittest.main()
