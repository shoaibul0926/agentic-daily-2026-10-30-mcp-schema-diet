import argparse
import json
import sys

from . import core


def _read(path):
    fh = sys.stdin if path == "-" else open(path, encoding="utf-8")
    with fh:
        return core.load_tools(json.load(fh))


def cmd_audit(args):
    tools = _read(args.file)
    rep = core.analyse(tools, budget=args.budget)
    if args.json:
        print(json.dumps(rep, indent=2))
    else:
        print(f"{rep['tool_count']} tools, ~{rep['total_tokens']} tokens (compact JSON; "
              f"{rep['pretty_printed_tokens']} if pretty-printed)\n")
        print(f"{'tool':<36}{'tokens':>7}{'desc':>7}  flags")
        for r in rep["tools"][: args.top]:
            flags = []
            if r["over_budget"]:
                flags.append(f"OVER BUDGET ({rep['budget']})")
            if r["long_description"]:
                flags.append("long description")
            if r["waste"]:
                flags.append("waste: " + ", ".join(f"{k}={v}" for k, v in r["waste"].items()))
            print(f"{r['name'][:35]:<36}{r['tokens']:>7}{r['description_tokens']:>7}  {'; '.join(flags)}")
        if rep["shared_properties"]:
            print("\nIdentical properties repeated across tools ($ref / hoisting candidates):")
            for s in rep["shared_properties"][:10]:
                print(f"  {s['property']:<16} in {s['tools']} tools, ~{s['reclaimable']} tokens reclaimable")
        lossless = core.analyse(core.slim(tools, "lossless"))["total_tokens"]
        aggr = core.analyse(core.slim(tools, "aggressive"))["total_tokens"]
        disc = core.analyse(core.slim(tools, "discovery"))["total_tokens"]
        print(f"\nIf slimmed:  lossless ~{lossless}   aggressive ~{aggr}   discovery-tier ~{disc}")
    over = [r for r in rep["tools"] if r["over_budget"]]
    return 1 if over else 0


def cmd_slim(args):
    tools = _read(args.file)
    result = core.slim(tools, args.level, args.max_desc)
    text = json.dumps({"tools": result}, separators=(",", ":"), ensure_ascii=False)
    if args.output:
        with open(args.output, "w", encoding="utf-8") as fh:
            fh.write(text + "\n")
    else:
        print(text)
    before, after = core.tokens(tools), core.tokens(result)
    print(f"{args.level}: ~{before} -> ~{after} tokens ({100 * (before - after) // max(before, 1)}% saved)",
          file=sys.stderr)
    return 0


def main(argv=None):
    p = argparse.ArgumentParser(prog="mcp-schema-diet", description=__doc__)
    sub = p.add_subparsers(dest="cmd", required=True)
    a = sub.add_parser("audit", help="report token cost and waste of a tools/list payload")
    a.add_argument("file", help="tools JSON file, or - for stdin")
    a.add_argument("--budget", type=int, help="per-tool token budget; exit 1 if any tool exceeds it")
    a.add_argument("--top", type=int, default=20)
    a.add_argument("--json", action="store_true")
    a.set_defaults(fn=cmd_audit)
    s = sub.add_parser("slim", help="write a slimmed copy of the tools")
    s.add_argument("file")
    s.add_argument("--level", choices=["lossless", "aggressive", "discovery"], default="lossless")
    s.add_argument("--max-desc", type=int, default=160)
    s.add_argument("-o", "--output")
    s.set_defaults(fn=cmd_slim)
    args = p.parse_args(argv)
    try:
        return args.fn(args)
    except (OSError, ValueError) as e:
        print(f"error: {e}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
