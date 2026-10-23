#!/usr/bin/env python3
"""Derive bounded input evidence from saved getevent -lt output, without ADB."""
import argparse
from collections import Counter
from decimal import Decimal
import hashlib
import json
from pathlib import Path
import re


def main():
    ap=argparse.ArgumentParser(description=__doc__)
    ap.add_argument("input",type=Path)
    ap.add_argument("output",type=Path)
    args=ap.parse_args()
    data=args.input.read_bytes()
    nodes={}; node=None; edges=[]; event_counts=Counter(); samples=[]; states={}; held=set()
    pattern=re.compile(r"^\[\s*([0-9.]+)\]\s+(/dev/input/event\d+):\s+(EV_\w+)\s+(\S+)\s+(\S+)")
    for line in data.decode(errors="replace").splitlines():
        if m:=re.match(r"add device \d+: (/dev/input/event\d+)",line): node=m[1]
        elif m:=re.match(r'\s+name:\s+"([^"]+)"',line):
            if node: nodes[node]=m[1]
        elif m:=pattern.match(line):
            timestamp,node,kind,code,value=m.groups();event_counts[node]+=1
            state=states.setdefault(node,{})
            if kind=="EV_KEY":
                edges.append({"time_seconds":timestamp,"node":node,"code":code,"value":value})
                key=(node,code)
                if value=="DOWN": held.add(key)
                elif value=="UP": held.discard(key)
            elif kind=="EV_ABS" and code in ("ABS_MT_POSITION_X","ABS_MT_POSITION_Y","ABS_MT_TRACKING_ID"):
                state[code]=int(value,16)
            elif kind=="EV_SYN" and code=="SYN_MT_REPORT":
                if "ABS_MT_POSITION_X" in state and "ABS_MT_POSITION_Y" in state:
                    samples.append({"time_seconds":timestamp,"node":node,"id":state.get("ABS_MT_TRACKING_ID"),"x":state["ABS_MT_POSITION_X"],"y":state["ABS_MT_POSITION_Y"]})
                state.clear()
    paired=[];downs={}
    for e in edges:
        key=(e["node"],e["code"])
        if e["value"]=="DOWN": downs[key]=e["time_seconds"]
        elif e["value"]=="UP" and key in downs:
            began=downs.pop(key)
            paired.append({"node":key[0],"code":key[1],"down_seconds":began,"up_seconds":e["time_seconds"],"held_ms":str((Decimal(e["time_seconds"])-Decimal(began))*1000)})
    summary={"source_sha256":hashlib.sha256(data).hexdigest(),"source_snapshot_bytes":len(data),
        "source_line_count":len(data.splitlines()),"registered_nodes":nodes,"event_counts":dict(event_counts),
        "observed_key_edges":edges,"paired_presses":paired,"touch_samples":samples,
        "touch_range":({"x_min":min(s["x"] for s in samples),"x_max":max(s["x"] for s in samples),"y_min":min(s["y"] for s in samples),"y_max":max(s["y"] for s in samples),"tracking_ids":sorted({s["id"] for s in samples if s["id"] is not None})} if samples else None),
        "held_keys_at_end":[{"node":n,"code":c} for n,c in sorted(held)],
        "limits":["Observed Android evdev reports, not raw AXS I2C packets", "Capture does not establish full screen edge coverage or multi-finger functionality", "No claim that an unreported device/button/gesture was tested", "Source hash covers this snapshot; rerun if recorder appends data"]}
    args.output.write_text(json.dumps(summary,indent=2)+"\n")
    print(json.dumps({"sha256":summary["source_sha256"],"events":sum(event_counts.values()),"touch_samples":len(samples),"range":summary["touch_range"]}))


if __name__=="__main__":main()
