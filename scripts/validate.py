#!/usr/bin/env python3
"""Static validator for the Zigbee Zabbix template YAML. Catches the schema-rule
violations that a live 7.4 import rejects, before hitting the network.

Run: python3 scripts/validate.py
Exit 0 = all checks pass; exit 1 = a violation (message names the file/rule).
"""
import glob
import os
import re
import sys
from collections import Counter

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SHARED_GROUP = "9702754414644deba5cb4ed3e9f33594"  # Templates/IoT — intentionally shared


def main():
    files = sorted(glob.glob(os.path.join(REPO, "templates", "**", "*.yaml"), recursive=True))
    if not files:
        print("no template YAML found under templates/", file=sys.stderr)
        return 1
    allu = []
    problems = []
    for f in files:
        txt = open(f, encoding="utf-8").read()
        rel = os.path.relpath(f, REPO)
        u = [x.lower() for x in re.findall(r"uuid:\s*([0-9a-f]{32})", txt)]
        for x in u:
            if not (x[12] == "4" and x[16] in "89ab"):
                problems.append("%s: uuid not valid v4: %s" % (rel, x))
        if "\t" in txt:
            problems.append("%s: tab character present (use 2-space indent)" % rel)
        if re.search(r"^  value_maps:", txt, re.M):
            problems.append("%s: value_maps at root (must be valuemaps: inside template)" % rel)
        if re.search(r"^      triggers:", txt, re.M):
            problems.append("%s: triggers inside template (must be root-level)" % rel)
        allu += u
    dupes = {k for k, v in Counter(allu).items() if v > 1}
    unexpected = dupes - {SHARED_GROUP}
    if unexpected:
        problems.append("cross-file duplicate UUIDs: %s" % ", ".join(sorted(unexpected)))
    if problems:
        for p in problems:
            print("FAIL  " + p, file=sys.stderr)
        return 1
    print("OK  %d template file(s) pass static validation." % len(files))
    return 0


if __name__ == "__main__":
    sys.exit(main())
