"""Host tests of the original no-I/O management protocol core."""
import ctypes as C
from pathlib import Path
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parent
DEFAULT = bytes.fromhex('02040600000411000000')
SET = bytes.fromhex('020402000003')
FULL = bytes.fromhex('020406000004db0e6801')

def crc(data):
    value = 0
    for b in data:
        value ^= b
        for _ in range(8):
            value = (value >> 1) ^ (0xA001 if value & 1 else 0)
    return value

def frame(data, full=False, seq=0, ack=0, channel=4):
    h = bytes([0x80 | (seq << 3) | (ack if full else 0),
               (channel << 4) | (len(data) >> 8), len(data) & 255])
    return h + bytes([sum(h) & 255 if full else 0]) + data + (
        crc(data) if full else 0).to_bytes(2, 'little')

def ack_frame(ack=0):
    return bytes([0x80 | ack, 0, 0, 0x80 | ack])

class Protocol(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp = tempfile.TemporaryDirectory()
        p = Path(cls.temp.name)
        (p/'wrap.c').write_text('#include "wmt_protocol.h"\n'
            'unsigned test_phase(struct cw_session*s){return s->phase;}\n'
            'unsigned test_events(struct cw_session*s){return s->events;}\n'
            'unsigned test_packets(struct cw_session*s){return s->packets;}\n'
            'unsigned test_size(void){return sizeof(struct cw_session);}\n')
        subprocess.run(['cc','-std=c99','-Wall','-Wextra','-Werror','-O2',
            '-fPIC','-shared','-I',str(ROOT),str(ROOT/'wmt_protocol.c'),
            str(p/'wrap.c'),'-o',str(p/'test.so')], check=True)
        cls.lib = C.CDLL(str(p/'test.so'))
        for name in ['test_phase','test_events','test_packets']:
            getattr(cls.lib,name).argtypes=[C.c_void_p]
        cls.lib.cw_init.argtypes=[C.c_void_p,C.c_uint]
        cls.lib.cw_poll.argtypes=[C.c_void_p,C.c_uint64]
        cls.lib.cw_command.argtypes=[C.c_void_p,C.c_int,C.c_uint64,C.c_uint64,
                                    C.c_void_p,C.c_size_t,C.c_void_p]
        cls.lib.cw_enter_full.argtypes=[C.c_void_p,C.c_uint64]
        cls.lib.cw_attest_pda_patch_reset.argtypes=[C.c_void_p,C.c_uint64]
        cls.lib.cw_feed.argtypes=[C.c_void_p,C.c_void_p,C.c_size_t,C.c_uint64]
        cls.lib.cw_take_ack.argtypes=[C.c_void_p,C.c_void_p]
        cls.lib.cw_crc16.argtypes=[C.c_void_p,C.c_size_t]
        cls.lib.cw_crc16.restype=C.c_uint16
    @classmethod
    def tearDownClass(cls):
        cls.temp.cleanup()
    def setUp(self):
        self.s=(C.c_uint64*((self.lib.test_size()+7)//8))()
        self.lib.cw_init(self.s,1)
    def command(self, cmd, now=100, timeout=100000):
        out=C.create_string_buffer(80);n=C.c_size_t()
        self.assertEqual(self.lib.cw_command(self.s,cmd,now,timeout,out,80,C.byref(n)),0)
        return out.raw[:n.value]
    def feed(self, data, now=200):
        return self.lib.cw_feed(self.s,data,len(data),now)
    def full_start(self):
        self.assertEqual(self.command(1),bytes.fromhex('8040050001040100040000'))
        self.assertEqual(self.feed(frame(DEFAULT)),0)
        self.assertEqual(self.lib.cw_attest_pda_patch_reset(self.s,250),0)
        self.assertEqual(self.command(2,300),bytes.fromhex('804009000104050003db0e68010000'))
        self.assertEqual(self.feed(frame(SET),400),0)
        self.assertEqual(self.lib.cw_enter_full(self.s,10400),0)
        self.assertEqual(self.command(3,10500),bytes.fromhex('874005cc01040100046cf3'))
    def test_crc_known_vector(self):
        self.assertEqual(self.lib.cw_crc16(b'123456789',9),0xbb3d)
    def test_default_off_and_invalid_enable(self):
        for enabled in [0,2,0xffffffff]:
            self.lib.cw_init(self.s,enabled)
            self.assertEqual(self.feed(b''),-1)
    def test_exact_three_command_handshake(self):
        self.full_start()
        self.assertEqual(self.feed(frame(FULL,True),10600),0)
        self.assertEqual(self.lib.test_phase(self.s),8)
        out=C.create_string_buffer(4)
        self.assertEqual(self.lib.cw_take_ack(self.s,out),0)
        self.assertEqual(out.raw,ack_frame())
        self.assertEqual(self.lib.test_events(self.s),3)
    def test_every_transport_split(self):
        data=frame(DEFAULT)
        for split in range(len(data)+1):
            self.lib.cw_init(self.s,1);self.command(1)
            self.assertEqual(self.feed(data[:split]),0)
            self.assertEqual(self.feed(data[split:]),0)
            self.assertEqual(self.lib.test_phase(self.s),3)
    def test_full_bytewise_split_and_delimiter(self):
        self.full_start()
        for byte in b'\x55\x55'+frame(FULL,True):
            self.assertEqual(self.feed(bytes([byte]),10600),0)
        self.assertEqual(self.lib.test_phase(self.s),8)
    def test_wmt_split_across_stp_packets(self):
        self.full_start()
        self.assertEqual(self.feed(frame(FULL[:3],True)+frame(FULL[3:],True,seq=1),10600),0)
        self.assertEqual(self.lib.test_phase(self.s),8)
    def test_ack_and_event_coalesced(self):
        self.full_start()
        self.assertEqual(self.feed(ack_frame()+frame(FULL,True),10600),0)
        self.assertEqual(self.lib.test_phase(self.s),8)
    def test_event_waits_for_command_ack(self):
        self.full_start()
        self.assertEqual(self.feed(frame(FULL,True,ack=7),10600),0)
        self.assertEqual(self.lib.test_phase(self.s),7)
        self.assertEqual(self.feed(ack_frame(),10700),0)
        self.assertEqual(self.lib.test_phase(self.s),8)
    def test_crc_error_sticky(self):
        self.full_start();p=bytearray(frame(FULL,True));p[-1]^=1
        self.assertEqual(self.feed(bytes(p),10600),-6)
        self.assertEqual(self.feed(frame(FULL,True),10700),-6)
        self.assertEqual(self.lib.test_events(self.s),2)
    def test_checksum_error(self):
        self.full_start();p=bytearray(frame(FULL,True));p[3]^=1
        self.assertEqual(self.feed(bytes(p),10600),-5)
    def test_wrong_opcode_status_and_options(self):
        for at, value, err in [(1,7,-11),(4,1,-12),(6,0x12,-11)]:
            self.lib.cw_init(self.s,1);self.command(1);p=bytearray(DEFAULT);p[at]=value
            self.assertEqual(self.feed(frame(p)),err)
            self.assertEqual(self.lib.test_events(self.s),0)
    def test_wrong_channel_sequence_ack_nak(self):
        for data,err in [(frame(FULL,True,channel=3),-8),
                         (frame(FULL,True,seq=1),-9),
                         (frame(FULL,True,ack=2),-10),
                         (bytes.fromhex('80c00a4a'),-4)]:
            self.lib.cw_init(self.s,1);self.full_start()
            self.assertEqual(self.feed(data,10600),err)
    def test_oversize_outer_and_inner(self):
        self.command(1)
        self.assertEqual(self.feed(bytes.fromhex('80480000')),-7)
        self.lib.cw_init(self.s,1);self.command(1)
        self.assertEqual(self.feed(frame(bytes.fromhex('0204ffff'))),-7)
    def test_mandatory_zero_tail_and_checksum(self):
        for offset,err in [(3,-5),(-1,-6)]:
            self.lib.cw_init(self.s,1);self.command(1);p=bytearray(frame(DEFAULT));p[offset]=1
            self.assertEqual(self.feed(bytes(p)),err)
    def test_timeout_partial_and_backward_clock(self):
        self.command(1,100,1000)
        self.assertEqual(self.feed(b'\x80',1099),0)
        self.assertEqual(self.feed(frame(DEFAULT)[1:],1100),-13)
        self.lib.cw_init(self.s,1);self.command(1)
        self.assertEqual(self.feed(b'',99),-14)
    def test_frozen_clock_budget(self):
        self.command(1)
        for _ in range(1000000):
            self.assertEqual(self.lib.cw_poll(self.s,100),0)
        self.assertEqual(self.lib.cw_poll(self.s,100),-15)
    def test_explicit_switch_and_wait(self):
        self.command(1);self.feed(frame(DEFAULT));self.lib.cw_attest_pda_patch_reset(self.s,250);self.command(2,300);self.feed(frame(SET),400)
        self.assertEqual(self.lib.cw_enter_full(self.s,10399),-3)
        self.assertEqual(self.lib.cw_enter_full(self.s,10400),0)
    def test_mode_switch_deadline(self):
        self.command(1);self.feed(frame(DEFAULT));self.lib.cw_attest_pda_patch_reset(self.s,250);self.command(2,300,1000);self.feed(frame(SET),400)
        self.assertEqual(self.lib.cw_enter_full(self.s,10400),-13)
    def test_unsolicited_extra_event_rejected(self):
        self.command(1)
        self.assertEqual(self.feed(frame(DEFAULT)+frame(DEFAULT)),-3)
        self.assertEqual(self.lib.test_phase(self.s),9)
    def test_capacity_bounds_no_output(self):
        out=C.create_string_buffer(b'Z'*32);n=C.c_size_t(123)
        self.assertEqual(self.lib.cw_command(self.s,1,100,100000,out,10,C.byref(n)),-2)
        self.assertEqual(n.value,123);self.assertEqual(out.raw[:32],b'Z'*32)
        self.assertEqual(self.lib.test_phase(self.s),1)
    def test_unknown_transport_and_resync_rejected(self):
        self.full_start()
        self.assertEqual(self.feed(b'\x7f'*4,10600),-4)
    def test_pda_attestation_required(self):
        self.assertEqual(self.lib.cw_attest_pda_patch_reset(self.s,90),-3)
        self.command(1);self.feed(frame(DEFAULT))
        out=C.create_string_buffer(32);n=C.c_size_t()
        self.assertEqual(self.lib.cw_command(self.s,2,300,100000,out,32,C.byref(n)),-3)
        self.assertEqual(self.lib.test_phase(self.s),3)
        self.assertEqual(self.lib.cw_attest_pda_patch_reset(self.s,400),0)
        self.command(2,500)
    def test_duplicate_sequence_rejected(self):
        self.full_start()
        self.assertEqual(self.feed(frame(FULL[:3],True),10600),0)
        self.assertEqual(self.feed(frame(FULL[3:],True),10700),-9)
    def test_ack_regression_rejected(self):
        self.full_start()
        self.assertEqual(self.feed(ack_frame(),10600),0)
        self.assertEqual(self.feed(frame(FULL,True,ack=7),10700),-10)
    def test_deadline_overflow_rejected(self):
        out=C.create_string_buffer(32);n=C.c_size_t()
        self.assertEqual(self.lib.cw_command(self.s,1,2**64-100,1000,out,32,C.byref(n)),-2)
    def test_zero_payload_mandatory_rejected(self):
        self.command(1);self.assertEqual(self.feed(bytes.fromhex('80000000')),-8)

if __name__=='__main__': unittest.main()
