#!/usr/bin/env python3
"""Build the model catalog of each built-in platform (development only; decision D121).

It reads LiteLLM's ``model_prices_and_context_window.json`` as data, from a path and never from the
network, and writes one ``catalog.json`` next to the adapter of each platform. The package and the
tests never import this module, and nothing here runs when a user calls a model
(Requirement 65.3).

    uv run python scripts/build_catalog.py SOURCE.json --fetched 2026-11-13 [--out DIR]

``--fetched`` is the date the source was fetched: it is written in the file, and it is an argument
so that two runs on the same inputs give the same bytes. ``--out`` is the folder that holds one
folder per platform (default ``src/skye/models/plugins/providers``).

What a file keeps for each model: the limits (input, output, the minimum of the prompt cache), the
capabilities (a yes or a no for each), the input and output modalities, the endpoints, the family
that makes the model, the places and the routes it runs on, and a few rare fields. What is left out
on purpose: prices, retirement dates and successors, notes, the moving ``-latest`` names, every
model that generates images, video or audio, and every platform or route that no adapter of this
library calls.

The stages:
  1  read       keep our platforms and our kinds of model, drop the bookkeeping of the source
  2  normalise  one entry per model: limits, capability flags, modalities, endpoints, the rest
  3  geography  one model under ``us.``, ``eu.``, ``global.`` ... becomes one entry with its places
  4  platforms  the groups of the source become platforms; the family is read from the name
  5  encode     the names go in lists at the top; each model is one row of the same columns

Raises: ``SystemExit`` with the usage when the arguments are wrong; ``AssertionError`` when the
    source has a shape this script does not know (a capability that is not a yes or a no).
Missing: the standard library only.
"""
import collections
import json
import pathlib
import re
import sys
import zlib


def J(v):  # noqa: N802
    return json.dumps(v, sort_keys=True, separators=(",", ":"))


# ---------------------------------------- what to keep
SCALE = {"none": 1, "minimal": 2, "low": 4, "medium": 8, "high": 16, "xhigh": 32, "max": 64}
# The groups of the source that an adapter of this library calls. Left out: the Gemini API (the
# ``google`` adapter calls Vertex AI), Bedrock Mantle and Azure Foundry (no adapter calls them).
KEEP_PROVIDERS = {
    "anthropic",
    "openai",
    "cohere",
    "cohere_chat",
    "bedrock",
    "bedrock_converse",
    "azure",
}
# The platform of the source and the folder of its adapter in ``models/plugins/providers``.
FOLDER = {
    "anthropic": "anthropic",
    "openai": "openai",
    "cohere": "cohere",
    "bedrock": "bedrock",
    "azure": "azure",
    "vertex_ai": "google",
}
SOURCE_NAME = "BerriAI/litellm, model_prices_and_context_window.json (MIT)"
SOURCE_URL = "https://raw.githubusercontent.com/BerriAI/litellm/refs/heads/main/model_prices_and_context_window.json"
# The library generates no images, video or audio and calls only chat and embeddings.
OUT_OF_SCOPE_MODES = {
    "image_generation",
    "image_edit",
    "video_generation",
    "audio_speech",
    "realtime",
    "audio_transcription",
    "ocr",
    "completion",
    "vector_store",
    "guardrail",
    "moderation",
}
DROP_FIELDS = {"source", "deprecation_source", "comment", "litellm_provider"}
NOTE_KEYS = {"notes", "note", "comment", "calculation"}  # inside ``metadata``
PRICE = re.compile(r"cost|price|multiplier|uplift")
DROP_EXTRA = {"deprecation_date", "successor_model"}
PRICE_KEYS = ("us", "fast")  # inside ``provider_specific_entry``
LIMITS = ["max_input_tokens", "max_output_tokens", "prompt_cache_min_tokens"]
# The name of a capability is the ``supports_<name>`` of the source without the prefix,
# with these shorter names.
RENAME = {
    "parallel_function_calling": "parallel_tools",
    "xhigh_reasoning_effort": "effort_xhigh",
    "max_reasoning_effort": "effort_max",
    "minimal_reasoning_effort": "effort_minimal",
    "none_reasoning_effort": "effort_none",
    "low_reasoning_effort": "effort_low",
    "assistant_prefill": "prefill",
    "native_streaming": "streaming",
    "native_structured_output": "structured_output",
    "mid_conversation_system": "mid_chat_system",
    "parallel_tool_use_config": "parallel_tool_config",
    "forced_tool_use": "forced_tool",
    "bedrock_native_structured_output": "bedrock_structured",
    "bedrock_native_structured_output_by_default": "bedrock_structured_default",
    "prompt_cache_breakpoint": "cache_breakpoint",
    "embedding_image_input": "image_embedding",
    "anthropic_compaction": "compaction",
    "bedrock_converse_tool_result_images": "bedrock_tool_images",
    "bedrock_runtime_chat_completions_response_format": "bedrock_chat_response_format",
    "thinking_cache_preservation": "thinking_cache",
    "bedrock_runtime_chat_completions_tools_with_reasoning": "bedrock_chat_tools_reasoning",
    "bedrock_runtime_chat_completions_inline_reasoning": "bedrock_chat_inline_reasoning",
    "nova_canvas_image_edit": "nova_image_edit",
}
OTHER_FLAGS = (
    {  # yes-or-no fields that are not called ``supports_...`` but are capabilities all the same
        "thinking_always_on": "thinking_always",
        "thinking_on_by_default": "thinking_default",
        "bedrock_converse_supports_strict_tools": "bedrock_strict_tools",
        "use_openai_responses_path": "responses_path",
        "gemini_native_audio": "gemini_native_audio",
        "gemini_audio_only_live": "gemini_audio_only_live",
        "uses_embed_content": "embed_content",
    }
)
COLUMNS = [
    "max_input_tokens",
    "max_output_tokens",
    "prompt_cache_min_tokens",
    "supported",
    "unsupported",
    "input_modalities",
    "output_modalities",
    "endpoints",
    "family",
    "places",
    "routes",
    "route_overrides",
    "extra",
]


def kept_provider(p):
    return p in KEEP_PROVIDERS or (p or "").startswith("vertex_ai")


# ---------------------------------------- 1 and 2: read, normalise
def make_entry(group, key, raw):
    """One entry: a ``flat`` dict whose keys say what a value is (lim:, sup:, in, out, ep, x:)."""
    r = {f: v for f, v in raw.items() if f not in DROP_FIELDS}
    if isinstance(r.get("metadata"), dict):
        meta = {k: v for k, v in r["metadata"].items() if k not in NOTE_KEYS}
        if meta:
            r["metadata"] = meta
        else:
            del r["metadata"]
    mode = r.pop("mode")
    flat = {}
    for f in list(r):
        if f.startswith("supports_"):
            v = r.pop(f)
            assert isinstance(v, bool), (key, f)
            flat["sup:" + RENAME.get(f[9:], f[9:])] = v
    for orig, name in OTHER_FLAGS.items():
        if orig in r:
            v = r.pop(orig)
            assert isinstance(v, bool), (key, orig)
            flat["sup:" + name] = v
    if "reasoning_effort_levels" in r:
        r["reasoning_effort_levels"] = sum(SCALE[x] for x in r["reasoning_effort_levels"])
    for f in list(r):
        if PRICE.search(f) or f in DROP_EXTRA:
            del r[f]
    if "provider_specific_entry" in r:
        pse = {k: v for k, v in r["provider_specific_entry"].items() if k not in PRICE_KEYS}
        if pse:
            r["provider_specific_entry"] = pse
        else:
            del r["provider_specific_entry"]
    for n in LIMITS:
        if n in r:
            flat["lim:" + n] = r.pop(n)
    for field, k in (
        ("supported_modalities", "in"),
        ("supported_output_modalities", "out"),
        ("supported_endpoints", "ep"),
    ):
        if field in r:
            flat[k] = r.pop(field)
    for f, v in r.items():
        flat["x:" + f] = v
    return {"group": group, "mode": mode, "key": key, "flat": flat, "places": None}


def read(source):
    raw = json.load(open(source))
    raw.pop("sample_spec", None)
    by = collections.defaultdict(lambda: collections.defaultdict(list))
    for key, rec in raw.items():
        if (
            key == "fallback_generalizations" or "alias_of" in rec
        ):  # LiteLLM's own rules table and its moving ``-latest`` names
            continue
        group = rec.get("litellm_provider")
        if not kept_provider(group):
            continue
        e = make_entry(group, key, rec)
        if e["mode"] in OUT_OF_SCOPE_MODES:
            continue
        by[group][e["mode"]].append(e)
    return by


# ---------------------------------------- 3: geography
GEO = re.compile(r"^(global|us|eu|apac|au|jp|us-gov|ca)\.")
SLASH = re.compile(r"^(bedrock|azure)/([a-z0-9-]+)/(.+)$")


def strip_geo(k):
    m = GEO.match(k)
    if m:
        return k[m.end() :], m.group(1)
    m = SLASH.match(k)
    if m and (m.group(1) == "bedrock" or m.group(2) in ("eu", "us", "apac")):
        return m.group(1) + "/" + m.group(3), m.group(2)
    return k, ""


def rebuild_id(base, label):
    if not label:
        return base
    if base.startswith("bedrock/") or base.startswith("azure/"):
        a, b = base.split("/", 1)
        return a + "/" + label + "/" + b
    return label + "." + base


def geography(entries):
    """One model under several places becomes one entry; what differs stays with each place."""
    fam = collections.defaultdict(list)
    for e in entries:
        base, label = strip_geo(e["key"])
        fam[base].append((e, label))
    out = []
    for base, v in fam.items():
        labels = [label for _, label in v]
        if (
            len(v) == 1
            or len(set(labels)) < len(labels)
            or any(rebuild_id(base, label) != e["key"] for e, label in v)
        ):
            out += [e for e, _ in v]
            continue
        keys = sorted(set().union(*[set(e["flat"]) for e, _ in v]))
        famflat, over = {}, collections.defaultdict(dict)
        for key in keys:
            have = {e["key"]: e["flat"][key] for e, _ in v if key in e["flat"]}
            if len({J(x) for x in have.values()}) == 1:
                famflat[key] = next(iter(have.values()))
            else:
                for k, x in have.items():
                    over[k][key] = x
        ov = {label: over[e["key"]] for e, label in v if over.get(e["key"])}
        if ov:
            famflat["x:place_overrides"] = ov
        out.append(
            {
                "group": v[0][0]["group"],
                "mode": v[0][0]["mode"],
                "key": base,
                "flat": famflat,
                "places": labels,
            }
        )
    return out


# ---------------------------------------- 4: platforms
BEDROCK_ROUTE = {"bedrock": "invoke", "bedrock_converse": "converse", "bedrock_mantle": "mantle"}
PLATFORM = {
    "anthropic": "anthropic",
    "openai": "openai",
    "gemini": "gemini",
    "cohere": "cohere",
    "cohere_chat": "cohere",
    "azure": "azure",
    "azure_ai": "azure",
    **{g: "bedrock" for g in BEDROCK_ROUTE},
}
PREFIX = {
    "gemini": "gemini/",
    "azure": "azure/",
    "azure_ai": "azure_ai/",
    "cohere": "cohere/",
    "cohere_chat": "cohere/",
    "openai": "openai/",
}
REGION = re.compile(r"^([a-z]{2}(?:-gov)?-[a-z]+-\d)/(.+)$")
ZONE = re.compile(r"^(eu|us|apac|global|us-gov)/(.+)$")
VERTEX_FAMILY = {
    "vertex_ai-ai21_models": "ai21",
    "vertex_ai-anthropic_models": "anthropic",
    "vertex_ai-deepseek_models": "deepseek",
    "vertex_ai-llama_models": "meta",
    "vertex_ai-minimax_models": "minimax",
    "vertex_ai-mistral_models": "mistral",
    "vertex_ai-moonshot_models": "moonshot",
    "vertex_ai-qwen_models": "qwen",
    "vertex_ai-zai_models": "zai",
}
FAMILY_BY_NAME = [
    ("anthropic", r"claude"),
    (
        "openai",
        r"gpt|(^|/)o[134](-|$)|chatgpt|codex|computer-use|whisper|dall-e|(^|/)text-embedding",
    ),
    ("google", r"gemini|gemma|palm|embedding-00|text-unicorn|imagen|veo"),
    ("meta", r"llama"),
    ("mistral", r"mistral|codestral|ministral|pixtral|mixtral|devstral|magistral"),
    ("cohere", r"command|(^|/)embed-|rerank"),
    ("deepseek", r"deepseek"),
    ("qwen", r"qwen"),
    ("xai", r"grok"),
    ("microsoft", r"phi-|(^|/)mai-|microsoft"),
    ("moonshot", r"kimi|moonshot"),
    ("zai", r"glm|zai"),
    ("minimax", r"minimax"),
    ("ai21", r"jamba|j2-"),
    ("amazon", r"nova|titan"),
    ("nvidia", r"nemotron|nvidia"),
    ("writer", r"palmyra"),
]
VENDOR = re.compile(
    r"^(?:[a-z-]+\.)?(anthropic|openai|amazon|meta|mistral|qwen|cohere|deepseek|moonshotai|minimax|nvidia|ai21|writer|google|stability|twelvelabs|zai|xai)\."
)


def platform_of(group):
    return PLATFORM.get(group) or ("vertex_ai" if group.startswith("vertex_ai") else None)


def family_of(group, key, platform):
    if group in VERTEX_FAMILY:
        return VERTEX_FAMILY[group]
    s = key.lower()
    m = VENDOR.match(s)
    if m:
        return {"moonshotai": "moonshot"}.get(m.group(1), m.group(1))
    if platform == "vertex_ai" and "embedding" in s and "gpt" not in s:
        return "google"
    for name, pattern in FAMILY_BY_NAME:
        if re.search(pattern, s):
            return name
    return None


def parse(e):
    """The platform, the route, the id to call and the places of one entry."""
    group, key, places = e["group"], e["key"], e["places"] or []
    plat = platform_of(group)
    if plat == "bedrock":
        route = BEDROCK_ROUTE[group]
        if route == "converse":
            m = GEO.match(key)
            return (plat, route, key[m.end() :], [m.group(1)]) if m else (plat, route, key, places)
        k = key
        if route == "mantle" and k.startswith("bedrock_mantle/"):
            k = k[15:]
        elif route == "invoke" and k.startswith("bedrock/"):
            k = k[8:]
        m = REGION.match(k)
        if m and (route == "mantle" or key.startswith("bedrock/")):
            return plat, route, m.group(2), [m.group(1)]
        return plat, route, k, places
    for pre in (PREFIX.get(group), "vertex_ai/" if plat == "vertex_ai" else None):
        if pre and key.startswith(pre):
            key = key[len(pre) :]
            break
    route = None
    if plat == "azure":
        m = ZONE.match(key)
        if m:
            places, key = [m.group(1)], m.group(2)
        route = "foundry" if group == "azure_ai" else "openai"
    return plat, route, key, places


def by_label(places):
    return sorted(places, key=lambda x: (x != "", x))


def platforms(by):
    """The groups become platforms; one model reached by several routes becomes one entry."""
    items = []
    for group in sorted(by):
        for mode in by[group]:
            for e in geography(by[group][mode]):
                plat, route, base, pl = parse(e)
                items.append({"e": e, "plat": plat, "route": route, "base": base, "pl": pl})
    # Two entries that land on the same id, in the same place, with different data cannot be
    # told apart: keep their own ids.
    grp = collections.defaultdict(list)
    for i, it in enumerate(items):
        if it["plat"] != "bedrock":
            grp[(it["plat"], it["e"]["mode"], it["base"], it["route"])].append(i)
    for ids in grp.values():
        if any(
            set(items[a]["pl"] or [""]) & set(items[b]["pl"] or [""])
            and J(items[a]["e"]["flat"]) != J(items[b]["e"]["flat"])
            for a in ids
            for b in ids
            if a < b
        ):
            for i in ids:
                items[i]["base"] = items[i]["e"]["key"]
    fam = collections.defaultdict(lambda: collections.defaultdict(list))
    for it in items:
        fam[(it["plat"], it["e"]["mode"], it["base"])][it["route"] or "_"].append(it)
    merged = {}
    for (plat, mode, base), routes in fam.items():
        rflat, rplaces, byplace, groups = (
            {},
            {},
            collections.defaultdict(lambda: collections.defaultdict(dict)),
            set(),
        )
        for route, lst in routes.items():
            keys = sorted(set().union(*[set(it["e"]["flat"]) for it in lst]))
            rf = {}
            for k in keys:
                have = [(it["pl"], it["e"]["flat"][k]) for it in lst if k in it["e"]["flat"]]
                if len({J(v) for _, v in have}) == 1:
                    rf[k] = have[0][1]
                else:
                    top = collections.Counter(J(v) for _, v in have).most_common(1)[0][0]
                    rf[k] = next(v for _, v in have if J(v) == top)
                    for pl, v in have:
                        if J(v) != top:
                            for lab in pl or [""]:
                                byplace[route][lab][k] = v
            rflat[route] = rf
            rplaces[route] = by_label({p for it in lst for p in it["pl"]})
            groups |= {it["e"]["group"] for it in lst}
        keys = sorted(set().union(*[set(f) for f in rflat.values()]))
        real = [r for r in routes if r != "_"]
        famflat, over = {}, collections.defaultdict(dict)
        for k in keys:
            have = {r: f[k] for r, f in rflat.items() if k in f}
            if real and k == "x:place_overrides":
                # The places belong to the route that listed them: never to the whole model.
                for r, v in have.items():
                    over[r][k] = v
            elif len({J(v) for v in have.values()}) == 1:
                famflat[k] = next(iter(have.values()))
            else:
                for r, v in have.items():
                    over[r][k] = v
        if real:
            ov = {}
            for r in sorted(set(over) | set(byplace)):
                o = {"over": over.get(r, {}), "by_place": dict(byplace.get(r, {}))}
                if o["over"] or o["by_place"]:
                    ov[r] = o
            places, routes_col = None, {r: rplaces[r] for r in real}
        else:
            ov = {"by_place": dict(byplace["_"])} if byplace.get("_") else {}
            places, routes_col = rplaces["_"] or None, None
        fs = collections.Counter(family_of(g, base, plat) for g in sorted(groups))
        fs.pop(None, None)
        merged[(plat, mode, base)] = {
            "flat": famflat,
            "places": places,
            "routes": routes_col,
            "ov": ov or None,
            "family": fs.most_common(1)[0][0] if fs else None,
        }
    return merged


def count_flat(f, use):
    for k, v in f.items():
        if k.startswith("sup:"):
            use["sup"][k[4:]] += 1
        elif k == "in" or k == "out":
            for n in v:
                use["mod"][n] += 1
        elif k == "ep":
            for n in v:
                use["ep"][n] += 1
        elif k == "x:place_overrides":
            for fl in v.values():
                count_flat(fl, use)


def encode(merged):
    use = {k: collections.Counter() for k in ("sup", "mod", "ep")}
    fam_use = collections.Counter()
    for m in merged.values():
        count_flat(m["flat"], use)
        for r, o in (m["ov"] or {}).items():
            for fl in (
                ([o["over"]] + list(o["by_place"].values()))
                if r != "by_place"
                else list(o.values())
            ):
                count_flat(fl, use)
        if m["family"]:
            fam_use[m["family"]] += 1
    lists = {k: [n for n in sorted(use[k], key=lambda n: (-use[k][n], n))] for k in use}
    pos = {k: {n: i for i, n in enumerate(v)} for k, v in lists.items()}
    families = sorted(fam_use, key=lambda n: (-fam_use[n], n))
    fpos = {n: i for i, n in enumerate(families)}

    def lim_cols(f):
        return [f.get("lim:" + n) for n in LIMITS]

    def flags(f):
        yes = sorted(pos["sup"][k[4:]] for k, v in f.items() if k.startswith("sup:") and v is True)
        no = sorted(pos["sup"][k[4:]] for k, v in f.items() if k.startswith("sup:") and v is False)
        return yes or None, no or None

    def lst(f, k, kind):
        return [pos[kind][n] for n in f[k]] if k in f else None

    def record(f):  # the style used inside ``place_overrides``
        rec = {}
        lim = lim_cols(f)
        while lim and lim[-1] is None:
            lim.pop()
        if lim:
            rec["limits"] = lim
        yes, no = flags(f)
        if yes:
            rec["supported"] = yes
        if no:
            rec["unsupported"] = no
        for k, name, kind in (
            ("in", "input_modalities", "mod"),
            ("out", "output_modalities", "mod"),
            ("ep", "supported_endpoints", "ep"),
        ):
            if k in f:
                rec[name] = lst(f, k, kind)
        for k, v in f.items():
            if k.startswith("x:"):
                rec[k[2:]] = v
        return rec

    def extra(f):
        ex = {}
        for k, v in f.items():
            if k.startswith("x:"):
                ex[k[2:]] = (
                    {label: record(fl) for label, fl in v.items()}
                    if k == "x:place_overrides"
                    else v
                )
        return ex or None

    def columns(f):  # the style used inside ``route_overrides``
        c = {}
        for n in LIMITS:
            if "lim:" + n in f:
                c[n] = f["lim:" + n]
        yes, no = flags(f)
        if yes:
            c["supported"] = yes
        if no:
            c["unsupported"] = no
        for k, name, kind in (
            ("in", "input_modalities", "mod"),
            ("out", "output_modalities", "mod"),
            ("ep", "endpoints", "ep"),
        ):
            if k in f:
                c[name] = lst(f, k, kind)
        ex = extra(f)
        if ex:
            c["extra"] = ex
        return c

    def overrides(m):
        if not m["ov"]:
            return None
        if m["routes"] is None:
            return {"by_place": {lab: columns(fl) for lab, fl in m["ov"]["by_place"].items()}}
        out = {}
        for r, o in m["ov"].items():
            c = columns(o["over"])
            if o["by_place"]:
                c["by_place"] = {lab: columns(fl) for lab, fl in o["by_place"].items()}
            if c:
                out[r] = c
        return out or None

    models = {}
    for (plat, mode, base), m in sorted(merged.items()):
        f = m["flat"]
        yes, no = flags(f)
        row = lim_cols(f) + [
            yes,
            no,
            lst(f, "in", "mod"),
            lst(f, "out", "mod"),
            lst(f, "ep", "ep"),
            fpos.get(m["family"]),
            m["places"],
            m["routes"],
            overrides(m),
            extra(f),
        ]
        models.setdefault(plat, {}).setdefault(mode, {})[base] = row
    for p in models:
        models[p] = {m: models[p][m] for m in sorted(models[p], key=lambda m: -len(models[p][m]))}
    return {
        "reasoning_effort_scale": SCALE,
        "supports": lists["sup"],
        "modalities": lists["mod"],
        "endpoints": lists["ep"],
        "families": families,
        "columns": COLUMNS,
        "models": dict(sorted(models.items())),
    }


def render(doc):
    """The text of one catalog file: the lists first, then one model per line."""
    head = {k: v for k, v in doc.items() if k != "models"}
    lines = [json.dumps(head, indent=1)[:-2].rstrip() + ',\n "models": {']
    kinds = []
    for kind, rows in doc["models"].items():
        body = ",\n".join(
            f'   {json.dumps(k)}: {json.dumps(r, separators=(",", ":"))}' for k, r in rows.items()
        )
        kinds.append(f"  {json.dumps(kind)}: {{\n{body}\n  }}")
    lines.append(",\n".join(kinds) + "\n }\n}\n")
    return "\n".join(lines)


def main(argv):
    args = list(argv[1:])
    options = {"--fetched": None, "--out": "src/skye/models/plugins/providers"}
    for name in options:
        if name in args:
            i = args.index(name)
            options[name] = args[i + 1]
            del args[i : i + 2]
    if len(args) != 1 or not options["--fetched"]:
        sys.exit(__doc__)
    merged = platforms(read(args[0]))
    source = {"name": SOURCE_NAME, "url": SOURCE_URL, "fetched": options["--fetched"]}
    for platform in sorted({plat for plat, _, _ in merged}):
        if platform not in FOLDER:
            continue
        part = {key: m for key, m in merged.items() if key[0] == platform}
        doc = {"source": source, "platform": FOLDER[platform], **encode(part)}
        doc["models"] = doc["models"][platform]
        text = render(doc)
        path = pathlib.Path(options["--out"]) / FOLDER[platform] / "catalog.json"
        path.write_text(text, encoding="utf-8")
        small = json.dumps(json.loads(text), separators=(",", ":")).encode()
        count = sum(len(rows) for rows in doc["models"].values())
        packed = len(zlib.compress(small, 9)) / 1024
        print(f"{path}: {count} models, {len(text) / 1024:.1f} KB, {packed:.2f} KB compressed")


if __name__ == "__main__":
    main(sys.argv)
