# mcp-schema-diet

Audit and slim the token cost of an MCP server's `tools/list` payload. Pure Python stdlib, no dependencies.

## The real need this answers

Practitioners keep reporting that MCP tool definitions eat a large share of the context window before the agent does anything, and the protocol hasn't fixed it:

- **[MCP spec discussion #2812](https://github.com/modelcontextprotocol/modelcontextprotocol/discussions/2812)** (opened May 2026, closed by a maintainer Sept 25 2026 with no spec change): the author measured 11 real tools with Anthropic's `count_tokens`: ~1,000 tokens for heavy tools vs ~100 for light ones, "entirely in JSON Schema size". They estimated ~$390 of first-turn schema cost over 2,600 conversations. They asked for schema-efficiency budgets (≈300 tokens for discovery, ≈1,000 for invocation), a tiered discovery/invocation model, and a `schema_version`. A commenter added that generators leak boilerplate: Pydantic `title` fields, `zod-to-json-schema`'s `$schema` and `additionalProperties`, pretty-printed JSON.
- **[SEP-1576](https://github.com/modelcontextprotocol/modelcontextprotocol/issues/1576)** (opened Sept 2025, closed "dormant" June 2026): analysing the official GitHub MCP server's 60 tools, `owner` appears in 36 and `repo` in 39 of them, an identical property repeated in most schemas. It proposed `$ref` dedup and trimming optional content.

Both were closed without a protocol-level fix, so server authors currently have to shrink their own schemas by hand, with no tool telling them where the tokens go. This is the tool for that.

## What it does

```
python -m mcp_schema_diet audit  tools.json [--budget 300] [--top 20] [--json]
python -m mcp_schema_diet slim   tools.json --level lossless|aggressive|discovery [-o out.json]
```

Input: a `tools/list` result as a bare list, `{"tools": [...]}`, or a full JSON-RPC response (`-` reads stdin).

**audit** reports per-tool token cost (compact JSON, as the model sees it) and how much is description text. It flags the boilerplate named in the sources above: `$schema`, auto-generated `title`s, `additionalProperties:false`, and `outputSchema`. It lists identical properties repeated across tools (the `owner`/`repo` pattern, with reclaimable tokens). It also shows what each slimming level would save. With `--budget N` it exits `1` if any tool exceeds N tokens, so it can gate CI.

**slim** writes a reduced copy:

| level | what changes | risk |
|---|---|---|
| `lossless` | drops `$schema` and `title`s that merely restate the property name | none for the model |
| `aggressive` | also drops `additionalProperties:false`; trims every description to its first sentence | review: descriptions lose detail |
| `discovery` | tier-1 view only: name, one-line description, `param: type` (`?` = optional) | meant for the "discovery tier" the discussion proposes; not a valid input schema |

Example (`examples/github_like_tools.json`, a 7-tool GitHub-style fixture):

```
7 tools, ~1063 tokens (compact JSON; 1579 if pretty-printed)
...
Identical properties repeated across tools: owner in 6 tools, repo in 6 tools
If slimmed:  lossless ~885   aggressive ~736   discovery-tier ~268
```

## Limitations

- Token counts are a `chars/4` estimate, not a real tokenizer; use them for relative comparison, and confirm with your provider's count API.
- It does not rewrite schemas to use `$ref`; it only reports the candidates, since client support for `$ref` is uneven (SEP-1576 itself flags this).
- Slimming is a local transform; it is not an MCP proxy.

## Run / test

```
python -m unittest discover -s tests
python -m mcp_schema_diet audit examples/github_like_tools.json --budget 150
```
