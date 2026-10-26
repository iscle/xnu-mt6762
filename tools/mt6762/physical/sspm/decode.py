#!/usr/bin/env python3
"""Validate a retained SSPM probe record against its intended image identity.

This decoder returns observations only. Zero cannot distinguish data from RAZ;
no decoded result authorizes SSPM commands, ACKs, PLL or voltage writes.
"""
import argparse
import hashlib
import json
from pathlib import Path
import struct

SIZE = 1024
ADDRESSES = (0x110c00, 0x110c04, 0x110c08, 0x110c0c, 0x110ea0,
             0x10450000, 0x10450004, 0x10450008, 0x1045000c,
             0x10450010, 0x10450014, 0x10450018, 0x10451004)
EXTERNAL = (0x10000040, 0x10000090, 0x100010c8, 0x1000c23c, 0x1000c240,
            0x1000c248, 0x10006350, 0x10006358, 0x1001a010, 0x1001a024,
            0x1001a050, 0x1001a054, 0x1001a058)
SCREEN_MASK = (0x83, 0x83, 1 << 17, 0xffffffff, 0xffffffff, 0xffffffff, 0xffffffff, 0x10013)
SCREEN_VALUE = (1, 1, 0, 0xd4800181, 0x81150000, 0x80000001, 0xffff0000, 0x12)
STATES = {1: 'running', 2: 'complete', 3: 'synchronous_abort', 4: 'refused', 5: 'expired'}
REASONS = {0: 'none', 1: 'entry', 2: 'external_profile', 3: 'guard_rejected',
           4: 'dispatch_budget', 5: 'reversed_time'}


def require(condition, message):
    if not condition:
        raise ValueError(message)


def decode(raw, identity, load_pc, physical_vectors):
    require(len(raw) == SIZE, 'record must be exactly 1024 bytes')
    require(len(identity) == 32 and raw[16:48] == identity, 'image identity mismatch')
    require(raw[:8] == b'MTKSSPR1', 'record magic mismatch')
    require(struct.unpack_from('<II', raw, 8) == (1, SIZE), 'record version/size mismatch')
    require(load_pc > 0 and load_pc % 4 == 0, 'invalid expected load PC')
    require(physical_vectors > 0 and physical_vectors % 2048 == 0, 'invalid expected VBAR')
    state, inverse, sequence, seq_inverse = struct.unpack_from('<4I', raw, 48)
    require(state in STATES and inverse == state ^ 0xffffffff, 'state not committed')
    require(0 < sequence <= 60 and seq_inverse == sequence ^ 0xffffffff, 'sequence not committed')
    reason, completed, index, passno, screens, bad_word = struct.unpack_from('<6I', raw, 64)
    require(reason in REASONS and completed <= 26 and screens <= 6, 'invalid progress counts/reason')
    began, ended, budget, hz = struct.unpack_from('<4Q', raw, 88)
    esr, far, elr, spsr = struct.unpack_from('<4Q', raw, 120)
    external = struct.unpack_from('<13I', raw, 152)
    external_valid, = struct.unpack_from('<I', raw, 204)
    mpidr, sctlr, vbar, daif = struct.unpack_from('<4Q', raw, 208)
    operation, = struct.unpack_from('<I', raw, 240)
    require(operation in (0, 1, 2), 'invalid operation')
    require(raw[244:256] == bytes(12) and raw[880:] == bytes(144), 'nonzero reserved bytes')
    require(external_valid < (1 << 13) and external_valid & (external_valid + 1) == 0,
            'external observation validity is not a prefix')
    require(budget == 130000, 'unexpected dispatch budget')
    words, valid_order, observed_values = [], [], []
    for i, address in enumerate(ADDRESSES):
        addr, first, second, valid, t0, t1, e0, e1 = struct.unpack_from('<4I4Q', raw, 256+i*48)
        require(addr == address and valid in (0, 1, 3), 'wrong word address/pass validity')
        value = (first, second); starts = (t0, t1); ends = (e0, e1)
        for p in range(2):
            if valid & (1 << p):
                valid_order.append(p*13+i); observed_values.append(value[p])
                if reason != 5:
                    require(began <= starts[p] <= ends[p], 'invalid completed-read timestamps')
            else:
                require(value[p] == 0, 'uncommitted value is nonzero')
        words.append({'address': hex(addr), 'valid': valid,
                      'first': first if valid & 1 else None,
                      'second': second if valid & 2 else None,
                      'stable': first == second if valid == 3 else None,
                      'began_ticks': list(starts), 'ended_ticks': list(ends)})
    require(sorted(valid_order) == list(range(completed)), 'completed reads are not the declared prefix')
    admitted = not (state == 4 and reason == 1)
    if admitted:
        require(hz == 13000000 and mpidr & 0xff00ffffff == 0 and sctlr & 0x2000005 == 0 and
                vbar == physical_vectors and daif & 0x3c0 == 0x3c0, 'entry profile mismatch')
    require((index < 13 and passno < 2) or (index == passno == 0xffffffff and completed == 0),
            'invalid active index/pass')
    if state in (2, 3):
        require(reason == 0 and external_valid == 0x1fff and bad_word == 0xffffffff,
                'completed/fault result lacks admitted external screen')
        require(all(external[i] & SCREEN_MASK[i] == SCREEN_VALUE[i] for i in range(8)),
                'completed/fault result has mismatched external profile')
    if state == 2:
        require(completed == 26 and index == 12 and passno == 1 and screens == 6 and operation == 0,
                'incomplete complete record')
        require(not (esr or far or elr or spsr) and began <= ended, 'complete record has fault/time anomaly')
        classification = 'completed_nonzero' if any(observed_values) else 'completed_zero'
    elif state == 3:
        require(index < 13 and passno < 2 and completed == passno*13+index and operation == 2,
                'abort is not at first uncompleted read')
        require(esr & 0xfe000000 == 0x96000000 and esr & 0x5ff == 0x10 and
                far == ADDRESSES[index] and elr == load_pc and spsr & 0x1f == 5 and
                spsr & 0x3c0 == 0x3c0, 'abort does not match guarded-load predicate')
        classification = 'synchronous_abort'
    else:
        # A reset may interrupt the handler between metadata stores and the
        # terminal C commit. Retain those bytes as uncommitted observations;
        # they are not sufficient to classify a synchronous abort.
        if state != 1:
            require(not (esr or far or elr or spsr), 'non-abort terminal record carries fault state')
        classification = 'incomplete'
        if state == 4 and reason == 1:
            require(completed == screens == external_valid == 0 and index == passno == 0xffffffff,
                    'entry refusal contains protected progress')
        elif state == 4 and reason == 2:
            require(operation == 1 and bad_word < 8 and external_valid == (1 << (bad_word+1))-1 and
                    external[bad_word] & SCREEN_MASK[bad_word] != SCREEN_VALUE[bad_word],
                    'profile refusal does not identify its observed mismatch')
        elif state == 4:
            require(reason == 3 and operation == 2, 'unknown refusal state')
        elif state == 5:
            require(reason in (4, 5), 'expiry without deadline/time reason')
    return {'schema': 'mt6762-guarded-sspm-read-v1', 'record_sha256': hashlib.sha256(raw).hexdigest(),
            'identity': identity.hex(), 'state': STATES[state], 'classification': classification,
            'reason': REASONS[reason], 'completed_reads': completed, 'sequence': sequence,
            'current_index': index, 'current_pass': passno, 'operation': operation,
            'screen_count': screens, 'external_valid': external_valid, 'bad_screen_word': bad_word,
            'began_ticks': began, 'ended_ticks': ended, 'dispatch_budget_ticks': budget,
            'counter_hz': hz, 'fault': {k: hex(v) for k, v in zip(('esr', 'far', 'elr', 'spsr'), (esr, far, elr, spsr))},
            'fault_committed': state == 3,
            'latest_external': [{'address': hex(a), 'value': v if external_valid & (1 << i) else None}
                                for i, (a, v) in enumerate(zip(EXTERNAL, external))],
            'words': words, 'sspm_ownership_granted': False, 'dvfs_granted': False,
            'limitations': ['Zero cannot distinguish real contents from read-as-zero.',
                'Completion proves only the recorded accesses at that instant, not firmware identity or ownership.',
                'Stalled bus/barrier, delayed SError and EL2/EL3 faults are not contained.',
                'Identity/inverse checks are not an authenticated record or whole-record checksum.']}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('record', type=Path)
    parser.add_argument('--identity', required=True, help='expected 32-byte image identity in hex')
    parser.add_argument('--load-pc', type=lambda s: int(s, 0), required=True)
    parser.add_argument('--physical-vectors', type=lambda s: int(s, 0), required=True)
    args = parser.parse_args()
    try:
        result = decode(args.record.read_bytes(), bytes.fromhex(args.identity), args.load_pc, args.physical_vectors)
    except (OSError, ValueError, struct.error) as error:
        parser.exit(1, 'SSPM record rejected: ' + str(error) + '\n')
    print(json.dumps(result, indent=2))


if __name__ == '__main__':
    main()
