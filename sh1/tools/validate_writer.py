"""Writer identity check: parse + rewrite every retail IPD and byte-compare.
Run: python validate_writer.py [disc_extract_dir]"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from sh1fmt import Ipd
from sh1fmt.writer import write_ipd

from sh1fmt import paths
BG = paths.bg_dir(sys.argv[1] if len(sys.argv) > 1 else None)


def main():
    ok = fail = 0
    failures = []
    for f in sorted(BG.glob("*.IPD")):
        raw = f.read_bytes()
        try:
            body = write_ipd(Ipd.parse(raw))
            full = body + raw[len(body):]
            if full == raw and len(body) <= len(raw):
                ok += 1
                continue
            div = next((i for i in range(min(len(full), len(raw)))
                        if full[i] != raw[i]), min(len(full), len(raw)))
            failures.append(f"{f.name}: first divergence at {div:#x} "
                            f"(body {len(body):#x} / file {len(raw):#x})")
        except Exception as e:
            failures.append(f"{f.name}: EXCEPTION {e}")
        fail += 1

    print(f"identity: {ok} OK, {fail} FAIL of {ok + fail}")
    for msg in failures[:25]:
        print(" ", msg)
    if len(failures) > 25:
        print(f"  ... and {len(failures) - 25} more")
    sys.exit(1 if fail else 0)


if __name__ == "__main__":
    main()
