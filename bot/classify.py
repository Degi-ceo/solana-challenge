#!/usr/bin/env python3
"""Memecoin classifier for candidate pools (task 3). Pure functions, no network.

Classes (analysis population = confirmed + probable, see docs/PREREGISTRATION.md):
  memecoin_confirmed  token came from a memecoin launchpad (RugCheck launchpad.platform, or a pump/bonk vanity mint)
  memecoin_probable   pool lives on a launchpad-family DEX but nothing confirms the origin yet
  not_memecoin        Jupiter-verified token (stocks, wrapped majors, DeFi tokens) or a pool that is far too deep to be a fresh launch
  unknown             nothing decides it

Order of evidence (first match wins) and WHY:
  1. RugCheck launchpad platform present      -> confirmed   (authoritative: the launchpad that created the mint)
  2. vanity mint ending in 'pump' / 'bonk'    -> confirmed   (pump.fun / LetsBonk generate these addresses)
  3. RugCheck jup_verified                    -> not_memecoin (verified listings: tokenised stocks, majors, DeFi)
  4. liquidity at first sight above $5M       -> not_memecoin (a fresh launch does not start that deep)
  5. launchpad-family DEX                     -> probable    (GeckoTerminal's dex label is NOT reliable: 'moonshot' pools were Meteora DBC tokens)
  6. otherwise                                -> unknown
Every result carries the reason so contamination is auditable.
"""

VANITY_SUFFIXES = ("pump", "bonk")
LAUNCHPAD_DEXES = {"pumpswap", "pump-fun", "meteora-dbc", "moonshot", "raydium-launchlab", "heaven", "boop-fun", "bags-fm"}
CURVE_DEXES = {"pump-fun", "meteora-dbc", "raydium-launchlab", "heaven", "boop-fun", "bags-fm"}   # pre-graduation bonding-curve pools
MAX_FRESH_LIQ_USD = 5_000_000


def classify(mint, dex=None, liq_usd=None, rugcheck=None):
    """rugcheck: optional dict {'launchpad_platform': str|None, 'jup_verified': bool|None}. Returns (class, reason)."""
    rc = rugcheck or {}
    platform = rc.get("launchpad_platform")
    if platform:
        return "memecoin_confirmed", f"rugcheck_launchpad:{platform}"
    if mint and mint.lower().endswith(VANITY_SUFFIXES):
        return "memecoin_confirmed", "vanity_mint:" + mint[-4:].lower()
    if rc.get("jup_verified"):
        return "not_memecoin", "jup_verified"
    if liq_usd is not None and liq_usd > MAX_FRESH_LIQ_USD:
        return "not_memecoin", "liquidity_gt_5m"
    if dex in LAUNCHPAD_DEXES:
        return "memecoin_probable", f"launchpad_dex:{dex}"
    return "unknown", "no_evidence"


def in_analysis_population(cls):
    return cls in ("memecoin_confirmed", "memecoin_probable")


def is_curve_pool(dex):
    """True for bonding-curve (pre-graduation) pools, which the graduation stream ignores."""
    return dex in CURVE_DEXES


def rugcheck_fields(report):
    """Extract the few fields the classifier and safety layer need from a RugCheck /report JSON (None-safe)."""
    r = report or {}
    lp = r.get("launchpad") or {}
    ver = r.get("verification")
    jup = ver.get("jup_verified") if isinstance(ver, dict) else (bool(ver) if ver is not None else None)
    return {"launchpad_platform": lp.get("platform") if isinstance(lp, dict) else None, "jup_verified": jup,
            "token_launch_ts": _iso_to_ts(r.get("detectedAt"))}


def _iso_to_ts(s):
    import calendar
    import time
    if not s:
        return None
    try:
        return calendar.timegm(time.strptime(str(s)[:19], "%Y-%m-%dT%H:%M:%S"))
    except ValueError:
        return None
