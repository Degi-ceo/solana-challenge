#!/usr/bin/env python3
"""Candidate discovery from several public sources, every candidate tagged with where it came from.

Why tags: each source has a different bias (paid promotion, trending = already pumped, new pools = brand new, top volume = established).
The funnel report compares pass rates per source so the bias can be measured instead of guessed.

Sources (tag -> endpoint):
  ds_boost_top, ds_boost_latest, ds_profile   DexScreener boosts / profiles  = PAID promotion
  ds_search                                    DexScreener search queries (organic, broad, noisy)
  gt_trending                                  GeckoTerminal trending pools (1h/6h/24h)
  gt_new                                       GeckoTerminal newest pools
  gt_volume                                    GeckoTerminal top pools by 24h volume

discover(cfg) -> {mint: "tag1+tag2"}  (tags sorted, de-duplicated by base-token mint)
Slow sources are cached (GeckoTerminal is rate limited to ~1 request / 5 s).
"""
import time

import bot

DS = "https://api.dexscreener.com"
GT = "https://api.geckoterminal.com/api/v2/networks/solana"
SOL = "So11111111111111111111111111111111111111112"
USDC = "EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v"
USDT = "Es9vMFrzaCERmJfrF4H2FYD4KCoNkY11McCe8BenwNYB"
QUOTE_MINTS = {SOL, USDC, USDT}          # never a candidate themselves
PAID = {"ds_boost_top", "ds_boost_latest", "ds_profile"}

DEFAULTS = {
    "ds_queries": ["pump", "meme", "dog", "cat", "pepe", "ai", "trump", "sol", "coin", "inu", "moon", "baby"],
    "gt_trending": [["24h", 2], ["6h", 1], ["1h", 1]],     # (duration, pages)
    "gt_new_pages": 2,
    "gt_volume_pages": 3,
    "ds_cache_s": 300,
    "gt_cache_s": 900,
}
_cache = {}


def _cached(key, ttl, fn, now):
    hit = _cache.get(key)
    if hit and now - hit[0] < ttl:
        return hit[1]
    val = fn()
    if val:                               # never cache an empty result (could be an outage)
        _cache[key] = (now, val)
        return val
    return hit[1] if hit else val          # on failure fall back to the last good result


def clear_cache():
    _cache.clear()


# ---------------------------------------------------------------- parsers (pure, fixture-tested)

def parse_ds_tokens(rows, tag):
    """DexScreener boosts / profiles: list of {chainId, tokenAddress}."""
    out = {}
    for x in rows or []:
        if isinstance(x, dict) and x.get("chainId") == "solana" and x.get("tokenAddress") and x["tokenAddress"] not in QUOTE_MINTS:
            out.setdefault(x["tokenAddress"], tag)
    return out


def parse_ds_search(j, tag="ds_search"):
    """DexScreener search: {pairs: [...]}; keep Solana pairs, base token only."""
    out = {}
    for p in (j or {}).get("pairs", []) or []:
        try:
            if p["chainId"] != "solana":
                continue
            m = p["baseToken"]["address"]
        except (KeyError, TypeError):
            continue
        if m not in QUOTE_MINTS:
            out.setdefault(m, tag)
    return out


def parse_gt_pools(j, tag):
    """GeckoTerminal pool listing: base-token mint from relationships.base_token.data.id = 'solana_<mint>'."""
    out = {}
    for d in (j or {}).get("data", []) or []:
        try:
            bid = d["relationships"]["base_token"]["data"]["id"]
        except (KeyError, TypeError):
            continue
        if bid.startswith("solana_"):
            m = bid.split("_", 1)[1]
            if m not in QUOTE_MINTS:
                out.setdefault(m, tag)
    return out


# ---------------------------------------------------------------- fetchers

def fetch_ds_paid():
    out = {}
    for tag, path in (("ds_boost_top", "/token-boosts/top/v1"), ("ds_boost_latest", "/token-boosts/latest/v1"), ("ds_profile", "/token-profiles/latest/v1")):
        for m, t in parse_ds_tokens(bot.http_json(DS + path), tag).items():
            out.setdefault(m, set()).add(t)
    return out


def fetch_ds_search(queries):
    out = {}
    for q in queries:
        for m, t in parse_ds_search(bot.http_json(f"{DS}/latest/dex/search?q={q}")).items():
            out.setdefault(m, set()).add(t)
    return out


def fetch_gt(cfg):
    import data                            # shares the GeckoTerminal rate limiter with the downloader
    out = {}

    def run(tag, path):
        for m, t in parse_gt_pools(data.gt_get(path), tag).items():
            out.setdefault(m, set()).add(t)

    for dur, pages in cfg["gt_trending"]:
        for p in range(1, pages + 1):
            run("gt_trending", f"/trending_pools?duration={dur}&page={p}")
    for p in range(1, cfg["gt_new_pages"] + 1):
        run("gt_new", f"/new_pools?page={p}")
    for p in range(1, cfg["gt_volume_pages"] + 1):
        run("gt_volume", f"/pools?sort=h24_volume_usd_desc&page={p}")
    return out


def discover(cfg=None, now=None):
    """Return {mint: 'tagA+tagB'}. cfg = the bot config (uses cfg['discovery'] overrides if present)."""
    now = now or time.time()
    c = dict(DEFAULTS, **((cfg or {}).get("discovery") or {}))
    merged = {}
    for src in (_cached("ds_paid", c["ds_cache_s"], fetch_ds_paid, now),
                _cached("ds_search", c["ds_cache_s"], lambda: fetch_ds_search(c["ds_queries"]), now),
                _cached("gt", c["gt_cache_s"], lambda: fetch_gt(c), now)):
        for m, tags in (src or {}).items():
            merged.setdefault(m, set()).update(tags)
    return {m: "+".join(sorted(t)) for m, t in merged.items()}


def split_tags(source):
    return [t for t in (source or "").split("+") if t]
