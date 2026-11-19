#!/usr/bin/env python3
"""Live swap executor for Jupiter, written to be SAFE BY DEFAULT. It is never run from the web sandbox and holds no keys.

How real trading is switched on (all of it is the OWNER's action, on the owner's own machine, with a dedicated burner wallet funded with a few dollars):
  1. config.json  "live": true
  2. environment   CONFIRM_LIVE=yes-burner-only
  3. environment   BURNER_KEYPAIR_PATH=/path/to/keypair.json   (owner-only permissions, outside this repository)
  4. a machine that is not an agent sandbox
Without all four, no transaction can be signed or sent: every send goes through Guard.assert_live(). Dry-run needs only a PUBLIC key (BURNER_PUBKEY): it quotes, builds,
validates and simulates the swap, and sends nothing. Hard caps below are constants in code; config can only tighten them.

Before signing, the swap transaction returned by the API is validated instruction by instruction (see validate_swap_tx): only known programs, the fee payer is the burner,
no transfer to any other address, token accounts created and closed only for the burner. A compromised or malicious API response is rejected instead of signed.
No seed phrase is ever read: the keypair file is the only secret, it is never logged, never copied, and the loader refuses a file inside the repository or readable by others.
"""
import base64
import json
import os
import struct
import time
from pathlib import Path

import bot

SOL = "So11111111111111111111111111111111111111112"
JUP = "https://api.jup.ag/swap/v1"
DEFAULT_RPC = "https://api.mainnet-beta.solana.com"
COMPUTE_BUDGET = "ComputeBudget111111111111111111111111111111"
SYSTEM = "11111111111111111111111111111111"
TOKEN = "TokenkegQfeZyiNwAJbNbGKPFXCWuBvf9Ss623VQ5DA"
TOKEN_2022 = "TokenzQdBNbLqP5VEhdkAS6EPFLC1PHnBqCXEpPxuEb"
ATA = "ATokenGPvbdGVxr1b2hvZbsiqW5xWH25efTNsLJA8knL"
JUPITER = "JUP6LkbZbjS1jKKwapdHNy74zcZ3tLUZoi5QNyVTaV4"
ALLOWED_PROGRAMS = {COMPUTE_BUDGET, SYSTEM, TOKEN, TOKEN_2022, ATA, JUPITER}
CONFIRM_VALUE = "yes-burner-only"
REPO = Path(__file__).resolve().parent.parent

# Hard caps in code. config["live_limits"] may only make them stricter.
CAPS = {"position_usd": 5.0, "max_open": 3, "daily_loss_usd": 3.0, "slippage_bps": 500, "impact_fraction": 0.03, "wallet_usd": 25.0, "priority_lamports": 500_000}
SOL_RESERVE_LAMPORTS = 10_000_000          # always keep 0.01 SOL for fees and rent
RENT_ALLOWANCE_LAMPORTS = 5_000_000        # extra lamports a swap transaction may move for account rent and wrapping


class Refused(Exception):
    """A safety rule blocked the action. Nothing was sent."""


# ---------------------------------------------------------------- environment and keys

def in_agent_sandbox(env=None, path_exists=os.path.exists):
    """Best-effort detection of a Claude Code / agent sandbox. Live trading is refused there (hard rule of this project)."""
    env = os.environ if env is None else env
    return any(k.startswith(("CLAUDE_CODE", "CCR_")) or k == "AI_AGENT" for k in env) or path_exists("/root/.ccr")


def effective_limits(cfg):
    lim = dict(CAPS)
    for k, v in (cfg.get("live_limits") or {}).items():
        if k in lim and isinstance(v, (int, float)) and v > 0:
            lim[k] = min(lim[k], v)                     # config can only tighten
    return lim


def load_keypair(path, repo=REPO):
    """Read a Solana CLI keypair file (JSON array of 64 bytes). Refuses unsafe locations and permissions. Never prints the content."""
    from solders.keypair import Keypair
    p = Path(path).expanduser().resolve()
    if not p.is_file():
        raise Refused(f"keypair file not found: {p.name}")
    try:
        p.relative_to(Path(repo).resolve())
        raise Refused("keypair file is inside the repository: move it out, it could be committed by accident")
    except ValueError:
        pass
    if os.name == "posix" and (p.stat().st_mode & 0o077):
        raise Refused("keypair file is readable by other users: run chmod 600 on it")
    try:
        raw = json.loads(p.read_text())
        if not (isinstance(raw, list) and len(raw) == 64 and all(isinstance(x, int) and 0 <= x < 256 for x in raw)):
            raise ValueError
        return Keypair.from_bytes(bytes(raw))
    except Exception:
        raise Refused("keypair file is not a Solana CLI keypair (a JSON array of 64 bytes)") from None


# ---------------------------------------------------------------- guard

class Guard:
    def __init__(self, cfg, env=None, kill=None, sandbox=None):
        self.cfg = cfg
        self.env = os.environ if env is None else env
        self.kill = bot.KILL if kill is None else kill
        self.sandbox = in_agent_sandbox if sandbox is None else sandbox
        self.limits = effective_limits(cfg)

    def why_not_live(self):
        """Reasons real transactions are NOT allowed right now. Empty list means allowed."""
        r = []
        if not self.cfg.get("live", False):
            r.append('config "live" is not true')
        if self.env.get("CONFIRM_LIVE") != CONFIRM_VALUE:
            r.append(f"CONFIRM_LIVE is not {CONFIRM_VALUE}")
        if not self.env.get("BURNER_KEYPAIR_PATH"):
            r.append("BURNER_KEYPAIR_PATH is not set")
        if self.sandbox():
            r.append("this looks like an agent sandbox: live trading is refused here")
        return r

    def assert_live(self):
        reasons = self.why_not_live()
        if reasons:
            raise Refused("live trading blocked: " + "; ".join(reasons))

    def check_buy(self, size_usd, n_open, daily_pnl_usd, slippage_bps, impact_fraction, wallet_usd=None):
        L = self.limits
        if Path(self.kill).exists():
            raise Refused("KILL file present: no new entries")
        if size_usd > L["position_usd"]:
            raise Refused(f"position ${size_usd:.2f} above the cap ${L['position_usd']:.2f}")
        if n_open >= L["max_open"]:
            raise Refused(f"already {n_open} open positions (cap {L['max_open']})")
        if daily_pnl_usd <= -L["daily_loss_usd"]:
            raise Refused(f"daily loss limit reached ({daily_pnl_usd:+.2f} USD)")
        if slippage_bps > L["slippage_bps"]:
            raise Refused(f"slippage {slippage_bps} bps above the cap {L['slippage_bps']}")
        if impact_fraction is not None and impact_fraction > L["impact_fraction"]:
            raise Refused(f"price impact {impact_fraction:.4f} above the cap {L['impact_fraction']}")
        if wallet_usd is not None and wallet_usd > L["wallet_usd"]:
            raise Refused(f"wallet holds about ${wallet_usd:.2f}, above the cap ${L['wallet_usd']:.0f}: this does not look like a burner wallet")

    def check_sell(self, slippage_bps):
        if slippage_bps > self.limits["slippage_bps"]:
            raise Refused(f"slippage {slippage_bps} bps above the cap {self.limits['slippage_bps']}")


# ---------------------------------------------------------------- transaction validation

def _pk(s):
    from solders.pubkey import Pubkey
    return Pubkey.from_string(s)


def ata_address(owner, mint, token_program=TOKEN):
    from solders.pubkey import Pubkey
    return str(Pubkey.find_program_address([bytes(_pk(owner)), bytes(_pk(token_program)), bytes(_pk(mint))], _pk(ATA))[0])


def validate_swap_tx(tx_b64, user, max_transfer_lamports):
    """Raise Refused unless the transaction only does what a Jupiter swap for `user` should do. Returns a short description."""
    from solders.transaction import VersionedTransaction
    tx = VersionedTransaction.from_bytes(base64.b64decode(tx_b64))
    m = tx.message
    keys = [str(k) for k in m.account_keys]
    if m.header.num_required_signatures != 1 or not keys or keys[0] != user:
        raise Refused("transaction is not a single-signer transaction paid by the burner wallet")
    wsol_ata = {ata_address(user, SOL, TOKEN)}
    res = lambda i: keys[i] if i < len(keys) else None            # indices beyond static keys come from lookup tables
    seen = []
    for ix in m.instructions:
        prog = keys[ix.program_id_index]
        seen.append(prog)
        if prog not in ALLOWED_PROGRAMS:
            raise Refused(f"transaction calls an unknown program: {prog}")
        acc, data = [res(i) for i in bytes(ix.accounts)], bytes(ix.data)
        if prog == SYSTEM:
            if len(data) != 12 or struct.unpack("<I", data[:4])[0] != 2:
                raise Refused("system program instruction other than a plain transfer")
            lamports = struct.unpack("<Q", data[4:])[0]
            if acc[0] != user or acc[1] not in wsol_ata or lamports > max_transfer_lamports:
                raise Refused("transfer to an address other than the burner's own wrapped-SOL account, or too large")
        elif prog in (TOKEN, TOKEN_2022):
            kind = data[:1]
            if kind == b"\x11":                                    # SyncNative
                continue
            if kind == b"\x09":                                    # CloseAccount: the rent must return to the burner
                if len(acc) < 3 or acc[1] != user or acc[2] != user:
                    raise Refused("token account closed to an address other than the burner")
                continue
            raise Refused("token program instruction other than SyncNative or CloseAccount")
        elif prog == ATA:
            if len(acc) < 3 or acc[2] != user or data[:1] not in (b"", b"\x00", b"\x01"):
                raise Refused("associated token account created for an owner other than the burner")
    if JUPITER not in seen:
        raise Refused("transaction does not contain the Jupiter swap instruction")
    return {"instructions": len(seen), "programs": sorted(set(seen))}


# ---------------------------------------------------------------- RPC and Jupiter clients

class Rpc:
    def __init__(self, url=None, http_json=None):
        self.url = url or os.environ.get("SOLANA_RPC_URL") or DEFAULT_RPC
        self.http = http_json or bot.http_json

    def call(self, method, params):
        r = self.http(self.url, {"jsonrpc": "2.0", "id": 1, "method": method, "params": params})
        if not r or "error" in r:
            raise RuntimeError(f"rpc {method} failed: {(r or {}).get('error', 'no response')}")
        return r["result"]

    def balance_lamports(self, pubkey):
        return int(self.call("getBalance", [pubkey, {"commitment": "confirmed"}])["value"])

    def token_balance(self, owner, mint):
        """(raw amount, token program id, token account address) for the burner's account of this mint, or (0, None, None)."""
        v = self.call("getTokenAccountsByOwner", [owner, {"mint": mint}, {"encoding": "jsonParsed", "commitment": "confirmed"}])["value"]
        total, prog, addr = 0, None, None
        for a in v:
            total += int(a["account"]["data"]["parsed"]["info"]["tokenAmount"]["amount"])
            prog, addr = a["account"]["owner"], a["pubkey"]
        return total, prog, addr

    def block_height(self):
        return int(self.call("getBlockHeight", [{"commitment": "confirmed"}]))

    def simulate(self, tx_b64):
        return self.call("simulateTransaction", [tx_b64, {"encoding": "base64", "sigVerify": False, "replaceRecentBlockhash": True, "commitment": "processed"}])["value"]

    def send(self, signed_b64):
        return self.call("sendTransaction", [signed_b64, {"encoding": "base64", "skipPreflight": False, "preflightCommitment": "confirmed", "maxRetries": 3}])

    def status(self, signature):
        v = self.call("getSignatureStatuses", [[signature], {"searchTransactionHistory": False}])["value"][0]
        return v


class Executor:
    def __init__(self, cfg, guard, rpc=None, http_json=None, keypair=None, pubkey=None, sleep=time.sleep):
        self.cfg, self.guard = cfg, guard
        self.http = http_json or bot.http_json
        self.rpc = rpc or Rpc(http_json=self.http)
        self.kp = keypair
        self.user = str(keypair.pubkey()) if keypair is not None else pubkey
        self.sleep = sleep

    # -- quoting and building (no side effects)
    def quote(self, in_mint, out_mint, amount, slippage_bps):
        q = self.http(f"{JUP}/quote?inputMint={in_mint}&outputMint={out_mint}&amount={int(amount)}&slippageBps={int(slippage_bps)}")
        if not q or "outAmount" not in q:
            raise Refused("no route")
        return q

    def build(self, quote):
        prio = min(int(self.cfg.get("priority_lamports", 100_000)), self.guard.limits["priority_lamports"])
        body = {"quoteResponse": quote, "userPublicKey": self.user, "wrapAndUnwrapSol": True, "dynamicComputeUnitLimit": True,
                "prioritizationFeeLamports": {"priorityLevelWithMaxLamports": {"maxLamports": prio, "priorityLevel": "high"}}}
        r = self.http(f"{JUP}/swap", body)
        if not r or "swapTransaction" not in r:
            raise Refused("the swap API did not return a transaction")
        return r

    def prepare(self, in_mint, out_mint, amount, slippage_bps, max_transfer_lamports):
        """quote -> build -> validate -> simulate. Returns everything needed to sign. Safe to call without any key."""
        if not self.user:
            raise Refused("no BURNER_PUBKEY / keypair: cannot build a transaction")
        q = self.quote(in_mint, out_mint, amount, slippage_bps)
        impact = float(q.get("priceImpactPct") or 0)          # unit is not documented to us: treated as a fraction, the stricter reading
        built = self.build(q)
        info = validate_swap_tx(built["swapTransaction"], self.user, max_transfer_lamports)
        sim = self.rpc.simulate(built["swapTransaction"])
        return {"quote": q, "impact_fraction": impact, "built": built, "tx": built["swapTransaction"], "validation": info, "simulation_error": sim.get("err"),
                "out_amount": int(q["outAmount"])}

    # -- signing and sending (live only)
    def _sign_send(self, tx_b64, last_valid_height, timeout_s=60):
        self.guard.assert_live()
        if self.kp is None:
            raise Refused("no keypair loaded")
        from solders.transaction import VersionedTransaction
        tx = VersionedTransaction.from_bytes(base64.b64decode(tx_b64))
        signed = VersionedTransaction(tx.message, [self.kp])
        sig = self.rpc.send(base64.b64encode(bytes(signed)).decode())
        deadline = time.time() + timeout_s
        while time.time() < deadline:
            st = self.rpc.status(sig)
            if st and st.get("err"):
                raise RuntimeError(f"transaction failed on chain: {st['err']}")
            if st and st.get("confirmationStatus") in ("confirmed", "finalized"):
                return sig
            if last_valid_height and self.rpc.block_height() > last_valid_height:
                raise RuntimeError("transaction expired before confirmation")
            self.sleep(2)
        raise RuntimeError("confirmation timed out")

    def wallet_usd(self, sol_usd):
        return self.rpc.balance_lamports(self.user) / 1e9 * sol_usd

    # -- high-level actions
    def buy(self, mint, size_usd, sol_usd, n_open, daily_pnl_usd, live):
        """Dry run (live=False) returns the prepared and simulated swap. Live also signs, sends, confirms and measures the fill."""
        slip = min(int(self.cfg.get("slippage_bps", 300)), self.guard.limits["slippage_bps"])
        lam = int(size_usd / sol_usd * 1e9)
        wallet_usd = self.wallet_usd(sol_usd) if (live or self.user) else None
        self.guard.check_buy(size_usd, n_open, daily_pnl_usd, slip, None, wallet_usd)
        prep = self.prepare(SOL, mint, lam, slip, lam + RENT_ALLOWANCE_LAMPORTS)
        self.guard.check_buy(size_usd, n_open, daily_pnl_usd, slip, prep["impact_fraction"], wallet_usd)
        if prep["built"].get("simulationError"):
            raise Refused(f"the swap API's own simulation failed: {prep['built']['simulationError']}")
        if prep["simulation_error"]:
            raise Refused(f"RPC simulation failed: {prep['simulation_error']}")
        if not live:
            return {"mode": "dry", **prep, "lamports_in": lam}
        self.guard.assert_live()
        if self.rpc.balance_lamports(self.user) < lam + SOL_RESERVE_LAMPORTS:
            raise Refused("not enough SOL in the burner wallet (a reserve for fees is always kept)")
        before_sol = self.rpc.balance_lamports(self.user)
        before_tok = self.rpc.token_balance(self.user, mint)[0]
        sig = self._sign_send(prep["tx"], prep["built"].get("lastValidBlockHeight"))
        after_sol = self.rpc.balance_lamports(self.user)
        after_tok, prog, acct = self.rpc.token_balance(self.user, mint)
        return {"mode": "live", "signature": sig, "lamports_spent": before_sol - after_sol, "tokens_raw": after_tok - before_tok, "token_program": prog, "token_account": acct}

    def sell(self, mint, amount_raw, live, close_account=True):
        slip = min(int(self.cfg.get("slippage_bps", 300)), self.guard.limits["slippage_bps"])
        self.guard.check_sell(slip)
        prep = self.prepare(mint, SOL, amount_raw, slip, RENT_ALLOWANCE_LAMPORTS)
        if prep["built"].get("simulationError") or prep["simulation_error"]:
            raise Refused(f"simulation failed: {prep['built'].get('simulationError') or prep['simulation_error']}")
        if not live:
            return {"mode": "dry", **prep}
        self.guard.assert_live()
        before = self.rpc.balance_lamports(self.user)
        sig = self._sign_send(prep["tx"], prep["built"].get("lastValidBlockHeight"))
        after = self.rpc.balance_lamports(self.user)
        out = {"mode": "live", "signature": sig, "lamports_received_sell_only": after - before}
        if close_account:
            out["close_signature"] = self.close_empty_account(mint)
            after = self.rpc.balance_lamports(self.user)           # includes the rent refund and both network fees
        out["lamports_received"] = after - before
        return out

    def close_empty_account(self, mint):
        """Close the burner's now-empty token account to get the rent (about 0.002 SOL) back. Does nothing if the account still holds tokens."""
        self.guard.assert_live()
        bal, prog, acct = self.rpc.token_balance(self.user, mint)
        if bal != 0 or not acct:
            return None
        from solders.hash import Hash
        from solders.instruction import AccountMeta, Instruction
        from solders.message import Message
        from solders.transaction import VersionedTransaction
        me = _pk(self.user)
        ix = Instruction(_pk(prog), bytes([9]), [AccountMeta(_pk(acct), False, True), AccountMeta(me, False, True), AccountMeta(me, True, False)])
        bh = Hash.from_string(self.rpc.call("getLatestBlockhash", [{"commitment": "confirmed"}])["value"]["blockhash"])
        tx = VersionedTransaction(Message.new_with_blockhash([ix], me, bh), [self.kp])
        sig = self.rpc.send(base64.b64encode(bytes(tx)).decode())
        return sig
