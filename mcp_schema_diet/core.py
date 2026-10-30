"""Core logic: load, measure, analyse and slim MCP tool definitions."""
import copy
import json
import math
import re
from collections import defaultdict

CHARS_PER_TOKEN = 4.0  # rough heuristic; real tokenizers vary by model


def load_tools(data):
    """Accept a bare list, {"tools": [...]}, or a JSON-RPC {"result": {"tools": [...]}}."""
    if isinstance(data, dict) and "result" in data:
        data = data["result"]
    if isinstance(data, dict) and "tools" in data:
        data = data["tools"]
    if not isinstance(data, list) or not all(isinstance(t, dict) and "name" in t for t in data):
        raise ValueError("expected a list of tools (or an object with a 'tools' list), each with a 'name'")
    return data


def compact(obj):
    return json.dumps(obj, separators=(",", ":"), ensure_ascii=False)


def tokens(obj):
    """Estimated token cost of a tool definition as the model would see it (compact JSON)."""
    text = obj if isinstance(obj, str) else compact(obj)
    return math.ceil(len(text) / CHARS_PER_TOKEN)


def _walk(node, path=()):
    yield path, node
    if isinstance(node, dict):
        for k, v in node.items():
            yield from _walk(v, path + (k,))
    elif isinstance(node, list):
        for i, v in enumerate(node):
            yield from _walk(v, path + (i,))


def _prettify(name):
    return re.sub(r"[_\-]+", " ", name).strip().title()


def _is_auto_title(prop_name, title):
    # Pydantic emits title = "Prop Name"; zod/others sometimes mirror the key.
    return isinstance(title, str) and title.lower() == _prettify(prop_name).lower()


def description_tokens(tool):
    total = 0
    for _, node in _walk(tool):
        if isinstance(node, dict):
            d = node.get("description")
            if isinstance(d, str):
                total += tokens(d)
    return total


def find_waste(tool):
    """Count tokens attributable to lossless-removable boilerplate in one tool."""
    waste = defaultdict(int)
    schema = tool.get("inputSchema") or {}
    for path, node in _walk(schema):
        if not isinstance(node, dict):
            continue
        if "$schema" in node:
            waste["$schema"] += tokens('"$schema":"%s",' % node["$schema"])
        if "additionalProperties" in node and node["additionalProperties"] is False:
            waste["additionalProperties:false"] += tokens('"additionalProperties":false,')
        props = node.get("properties")
        if isinstance(props, dict):
            for pname, psch in props.items():
                if isinstance(psch, dict) and _is_auto_title(pname, psch.get("title")):
                    waste["auto-generated title"] += tokens('"title":"%s",' % psch["title"])
    if "outputSchema" in tool:
        waste["outputSchema"] += tokens(tool["outputSchema"])
    return dict(waste)


def shared_properties(tools, min_tools=3):
    """Property schemas identical across several tools (hoisting / $ref candidates)."""
    seen = defaultdict(list)
    for t in tools:
        props = (t.get("inputSchema") or {}).get("properties") or {}
        for pname, psch in props.items():
            seen[(pname, compact(psch))].append(t["name"])
    out = []
    for (pname, blob), names in seen.items():
        if len(names) >= min_tools:
            one = tokens('"%s":%s,' % (pname, blob))
            out.append({"property": pname, "tools": len(names), "tokens_each": one,
                        "reclaimable": one * (len(names) - 1)})
    return sorted(out, key=lambda r: -r["reclaimable"])


def analyse(tools, budget=None, long_desc=60):
    rows = []
    for t in tools:
        cost = tokens(t)
        rows.append({
            "name": t["name"], "tokens": cost,
            "description_tokens": description_tokens(t),
            "waste": find_waste(t),
            "over_budget": budget is not None and cost > budget,
            "long_description": tokens(t.get("description", "")) > long_desc,
        })
    shared = shared_properties(tools)
    return {
        "tool_count": len(tools),
        "total_tokens": sum(r["tokens"] for r in rows),
        "pretty_printed_tokens": tokens(json.dumps(tools, indent=2)),
        "tools": sorted(rows, key=lambda r: -r["tokens"]),
        "shared_properties": shared,
        "budget": budget,
    }


def _first_sentence(text, limit):
    m = re.match(r"(.+?[.!?])(\s|$)", text.strip(), re.S)
    s = m.group(1) if m else text.strip()
    return s if len(s) <= limit else s[: limit - 1].rstrip() + "…"


def slim(tools, level="lossless", max_desc=160):
    """Return a slimmed copy.

    lossless  - drops $schema and auto-generated titles (no information lost for the model)
    aggressive- also drops additionalProperties:false and trims every description
                to its first sentence (max_desc chars) -- review before shipping
    discovery - tier-1 view: name, one-line description, parameter names/types/required marker
    """
    if level not in ("lossless", "aggressive", "discovery"):
        raise ValueError("unknown level: %s" % level)
    out = []
    for t in tools:
        if level == "discovery":
            props = (t.get("inputSchema") or {}).get("properties") or {}
            req = set((t.get("inputSchema") or {}).get("required") or [])
            params = {p: (s.get("type", "any") if isinstance(s, dict) else "any") + ("" if p in req else "?")
                      for p, s in props.items()}
            out.append({"name": t["name"],
                        "description": _first_sentence(t.get("description", ""), max_desc),
                        "params": params})
            continue
        t = copy.deepcopy(t)
        _strip(t.get("inputSchema"), level, max_desc)
        if level == "aggressive":
            if isinstance(t.get("description"), str):
                t["description"] = _first_sentence(t["description"], max_desc)
        out.append(t)
    return out


def _strip(node, level, max_desc):
    if isinstance(node, dict):
        node.pop("$schema", None)
        if level == "aggressive" and node.get("additionalProperties") is False:
            node.pop("additionalProperties")
        props = node.get("properties")
        if isinstance(props, dict):
            for pname, psch in props.items():
                if isinstance(psch, dict) and _is_auto_title(pname, psch.get("title")):
                    psch.pop("title")
        if level == "aggressive" and isinstance(node.get("description"), str):
            node["description"] = _first_sentence(node["description"], max_desc)
        for v in node.values():
            _strip(v, level, max_desc)
    elif isinstance(node, list):
        for v in node:
            _strip(v, level, max_desc)
