#!/usr/bin/env python3
"""Gate the port61-nomq target against the recorded device symbol gap.

The blocking symbol list comes from the device profile under
build/device-profiles/, so the gate follows the real kernel instead of a copy of
the list inside the workflow. A module that still imports any of those symbols
cannot be loaded there: kernel/module/main.c simplify_symbols() rejects every
non-weak undefined symbol with -ENOENT.
"""
import argparse
import json
import pathlib
import subprocess
import sys

ROOT = pathlib.Path(__file__).resolve().parents[1]
PROFILE = ROOT / 'build/device-profiles/6.1.138-android14-11.json'
PROJECT = ROOT / 'build/port61-nomq.json'


def readelf_symbols(module):
    out = subprocess.run(['readelf', '-sW', str(module)],
                         capture_output=True, text=True, check=True).stdout
    imported, defined = set(), set()
    for line in out.splitlines():
        if ' UND ' in line:
            fields = line.split()
            if len(fields) > 1 and fields[-1] != 'UND':
                imported.add(fields[-1])
        elif ' FUNC ' in line or ' OBJECT ' in line:
            fields = line.split()
            if len(fields) > 1 and fields[-1] not in ('FUNC', 'OBJECT'):
                defined.add(fields[-1])
    return imported, defined


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('module', help='built droidspaces_ns.ko')
    parser.add_argument('--profile', default=str(PROFILE))
    parser.add_argument('--project', default=str(PROJECT))
    args = parser.parse_args()

    module = pathlib.Path(args.module)
    if not module.is_file():
        print(f'gate: fail - {module} was not built', file=sys.stderr)
        return 1

    profile = json.loads(pathlib.Path(args.profile).read_text())
    project = json.loads(pathlib.Path(args.project).read_text())
    blocking = set(profile['blocking_symbol_gap']['absent_symbols'])
    blocking |= set(profile['absent_symbols_needed_by_a_self_owned_backend'])
    blocking |= set(profile['absent_symbols_tempting_for_the_mqueue_port'])
    required = project.get('required_defined_symbols', [])

    imported, defined = readelf_symbols(module)
    found = sorted(imported & blocking)
    absent = [name for name in required if name not in defined]

    print(f'{module.name}: {module.stat().st_size} bytes')
    print(f'imports={len(imported)} defined={len(defined)} '
          f'blocking_list={len(blocking)}')
    for name in found:
        print(f'  blocking symbol still imported: {name}')
    for name in absent:
        print(f'  expected backend symbol not defined yet: {name}')

    if found or absent:
        print('gate: fail - the module cannot load on the recorded device',
              file=sys.stderr)
        return 1
    print('gate: pass - the module neither imports a blocking symbol nor '
          'misses a backend symbol')
    return 0


if __name__ == '__main__':
    sys.exit(main())
