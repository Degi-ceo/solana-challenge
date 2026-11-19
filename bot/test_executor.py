import base64
import json
import os
import re
import stat
import struct
import subprocess
import tempfile
import unittest
from pathlib import Path

import executor as X

try:
    from solders.hash import Hash
    from solders.instruction import AccountMeta, Instruction
    from solders.keypair import Keypair
    from solders.message import Message
    from solders.pubkey import Pubkey
    from solders.transaction import VersionedTransaction
    HAVE = True
except ImportError:
    HAVE = False

FX = Path(__file__).parent / "fixtures"
SOLMINT = X.SOL
TOKMINT = "JUPyiwrYJFskUPiHa7hkeR8VUtAeFoSYbKedZNsDvCN"
TOKACCT = str(Keypair().pubkey()) if HAVE else "x"
GOOD_ENV = {"CONFIRM_LIVE": "yes-burner-only", "BURNER_KEYPAIR_PATH": "/x/key.json"}


def rnd():
    return str(Keypair().pubkey())


def ix(prog, data=b"", accounts=()):
    return Instruction(Pubkey.from_string(prog), data, [AccountMeta(Pubkey.from_string(a), s, w) for a, s, w in accounts])


def swap_tx(user_kp, extra=(), lamports=20_000_000, omit_jupiter=False, wrong_payer=None, close_to=None, ata_owner=None):
    user = str(user_kp.pubkey())
    wsol = X.ata_address(user, SOLMINT)
    out_ata = X.ata_address(user, TOKMINT)
    ixs = [ix(X.COMPUTE_BUDGET, b"\x02\x40\x0d\x03\x00"), ix(X.COMPUTE_BUDGET, b"\x03" + struct.pack("<Q", 71428)),
           ix(X.ATA, b"\x01", [(user, True, True), (wsol, False, True), (ata_owner or user, False, False), (SOLMINT, False, False), (X.SYSTEM, False, False), (X.TOKEN, False, False)]),
           ix(X.SYSTEM, struct.pack("<IQ", 2, lamports), [(user, True, True), (wsol, False, True)]),
           ix(X.TOKEN, b"\x11", [(wsol, False, True)]),
           ix(X.ATA, b"\x01", [(user, True, True), (out_ata, False, True), (user, False, False), (TOKMINT, False, False), (X.SYSTEM, False, False), (X.TOKEN, False, False)])]
    if not omit_jupiter:
        ixs.append(ix(X.JUPITER, b"route", [(user, True, True), (wsol, False, True), (out_ata, False, True)]))
    ixs.append(ix(X.TOKEN, b"\x09", [(wsol, False, True), (close_to or user, False, True), (user, True, False)]))
    ixs += list(extra)
    payer = Pubkey.from_string(wrong_payer) if wrong_payer else user_kp.pubkey()
    msg = Message.new_with_blockhash(ixs, payer, Hash.default())
    return base64.b64encode(bytes(VersionedTransaction(msg, [user_kp]) if not wrong_payer else VersionedTransaction.populate(msg, [__import__("solders.signature", fromlist=["Signature"]).Signature.default()]))).decode()


@unittest.skipUnless(HAVE, "solders not installed")
class TestValidation(unittest.TestCase):
    def setUp(self):
        self.kp = Keypair()
        self.user = str(self.kp.pubkey())

    def ok(self, tx, max_lamports=25_000_000):
        return X.validate_swap_tx(tx, self.user, max_lamports)

    def bad(self, tx, fragment, max_lamports=25_000_000):
        with self.assertRaises(X.Refused) as c:
            X.validate_swap_tx(tx, self.user, max_lamports)
        self.assertIn(fragment, str(c.exception))

    def test_real_jupiter_transaction_passes(self):
        fx = json.loads((FX / "jupiter_swap.json").read_text())
        info = X.validate_swap_tx(fx["tx_b64"], fx["user"], 20_000_000 + X.RENT_ALLOWANCE_LAMPORTS)
        self.assertIn(X.JUPITER, info["programs"])

    def test_benign_synthetic_transaction_passes(self):
        self.assertEqual(self.ok(swap_tx(self.kp))["instructions"], 8)

    def test_extra_transfer_to_an_attacker_is_rejected(self):
        evil = ix(X.SYSTEM, struct.pack("<IQ", 2, 5_000_000), [(self.user, True, True), (rnd(), False, True)])
        self.bad(swap_tx(self.kp, extra=[evil]), "other than the burner's own wrapped-SOL")

    def test_oversized_transfer_into_own_wsol_is_rejected(self):
        self.bad(swap_tx(self.kp, lamports=900_000_000), "too large")

    def test_unknown_program_is_rejected(self):
        self.bad(swap_tx(self.kp, extra=[ix(rnd(), b"x", [(self.user, True, True)])]), "unknown program")

    def test_token_account_closed_to_an_attacker_is_rejected(self):
        self.bad(swap_tx(self.kp, close_to=rnd()), "closed to an address other than the burner")

    def test_token_transfer_instruction_is_rejected(self):
        evil = ix(X.TOKEN, b"\x03" + struct.pack("<Q", 1), [(rnd(), False, True), (rnd(), False, True), (self.user, True, False)])
        self.bad(swap_tx(self.kp, extra=[evil]), "other than SyncNative or CloseAccount")

    def test_ata_created_for_another_owner_is_rejected(self):
        self.bad(swap_tx(self.kp, ata_owner=rnd()), "owner other than the burner")

    def test_system_instruction_other_than_transfer_is_rejected(self):
        evil = ix(X.SYSTEM, struct.pack("<I", 1) + b"x" * 8, [(self.user, True, True), (rnd(), False, True)])
        self.bad(swap_tx(self.kp, extra=[evil]), "other than a plain transfer")

    def test_missing_swap_instruction_is_rejected(self):
        self.bad(swap_tx(self.kp, omit_jupiter=True), "does not contain the Jupiter swap")

    def test_other_fee_payer_is_rejected(self):
        self.bad(swap_tx(self.kp, wrong_payer=rnd()), "single-signer transaction paid by the burner")


class TestLimitsAndEnvironment(unittest.TestCase):
    def test_config_can_only_tighten_caps(self):
        lim = X.effective_limits({"live_limits": {"position_usd": 1.0, "max_open": 99, "slippage_bps": 50, "wallet_usd": -5}})
        self.assertEqual((lim["position_usd"], lim["max_open"], lim["slippage_bps"], lim["wallet_usd"]), (1.0, X.CAPS["max_open"], 50, X.CAPS["wallet_usd"]))

    def test_sandbox_detection(self):
        self.assertTrue(X.in_agent_sandbox({"CLAUDE_CODE_SESSION_ID": "x"}, lambda p: False))
        self.assertTrue(X.in_agent_sandbox({"CCR_AGENT_PROXY_ENABLED": "1"}, lambda p: False))
        self.assertTrue(X.in_agent_sandbox({}, lambda p: p == "/root/.ccr"))
        self.assertFalse(X.in_agent_sandbox({"PATH": "/usr/bin"}, lambda p: False))

    @unittest.skipUnless(HAVE, "solders not installed")
    def test_keypair_loader_rules(self):
        d = tempfile.mkdtemp()
        kp = Keypair()
        good = Path(d) / "k.json"
        good.write_text(json.dumps(list(bytes(kp))))
        os.chmod(good, 0o600)
        self.assertEqual(str(X.load_keypair(good, repo=Path(d) / "elsewhere").pubkey()), str(kp.pubkey()))
        with self.assertRaises(X.Refused) as c:                                        # inside the repository
            X.load_keypair(good, repo=d)
        self.assertIn("inside the repository", str(c.exception))
        os.chmod(good, 0o644)
        with self.assertRaises(X.Refused) as c:
            X.load_keypair(good, repo=Path(d) / "elsewhere")
        self.assertIn("chmod 600", str(c.exception))
        os.chmod(good, 0o600)
        bad = Path(d) / "bad.json"
        bad.write_text("[1,2,3]")
        os.chmod(bad, 0o600)
        with self.assertRaises(X.Refused) as c:
            X.load_keypair(bad, repo=Path(d) / "elsewhere")
        self.assertNotIn("1,2,3", str(c.exception))                                    # never echoes file content
        with self.assertRaises(X.Refused):
            X.load_keypair(Path(d) / "missing.json", repo=Path(d) / "elsewhere")


class TestGuard(unittest.TestCase):
    def guard(self, cfg=None, env=None, sandbox=False, kill=None):
        return X.Guard(dict({"live": True}, **(cfg or {})), env=GOOD_ENV if env is None else env, kill=kill or "/nonexistent/KILL", sandbox=lambda: sandbox)

    def test_live_needs_every_condition(self):
        self.assertEqual(self.guard().why_not_live(), [])
        self.assertTrue(self.guard(cfg={"live": False}).why_not_live())
        self.assertTrue(self.guard(env={"BURNER_KEYPAIR_PATH": "/x"}).why_not_live())
        self.assertTrue(self.guard(env={"CONFIRM_LIVE": "yes"}).why_not_live())
        self.assertTrue(self.guard(env={"CONFIRM_LIVE": "yes-burner-only"}).why_not_live())
        self.assertTrue(self.guard(sandbox=True).why_not_live())                      # everything else right, still refused in a sandbox
        with self.assertRaises(X.Refused):
            self.guard(sandbox=True).assert_live()

    def test_default_config_is_not_live(self):
        self.assertTrue(X.Guard({}, env=GOOD_ENV, sandbox=lambda: False).why_not_live())

    def test_buy_limits(self):
        g = self.guard()
        g.check_buy(2.5, 0, 0.0, 300, 0.001, 5.0)
        for kw, frag in [(dict(size_usd=6.0), "above the cap"), (dict(n_open=3), "open positions"), (dict(daily_pnl_usd=-3.0), "daily loss"),
                         (dict(slippage_bps=900), "slippage"), (dict(impact_fraction=0.5), "price impact"), (dict(wallet_usd=500.0), "burner")]:
            args = dict(size_usd=2.5, n_open=0, daily_pnl_usd=0.0, slippage_bps=300, impact_fraction=0.001, wallet_usd=5.0)
            args.update(kw)
            with self.assertRaises(X.Refused, msg=frag) as c:
                g.check_buy(**args)
            self.assertIn(frag, str(c.exception))

    def test_kill_file_blocks_entries_but_not_exits(self):
        kill = Path(tempfile.mkdtemp()) / "KILL"
        kill.write_text("x")
        g = self.guard(kill=kill)
        with self.assertRaises(X.Refused):
            g.check_buy(2.5, 0, 0.0, 300, 0.0, 5.0)
        g.check_sell(300)                                                              # positions can still be closed


class FakeRpc:
    def __init__(self, balances=(100_000_000, 100_000_000 - 2_600_000), tokens=(0, 123456), sim_err=None, status="confirmed"):
        self.sent, self.calls, self.balances, self.tokens, self.sim_err, self._status = [], [], list(balances), list(tokens), sim_err, status
        self.bal_i = self.tok_i = 0

    def balance_lamports(self, pk):                       # the state before any transaction was sent, and the state after
        return self.balances[min(1 if self.sent else 0, len(self.balances) - 1)]

    def token_balance(self, owner, mint):
        return self.tokens[min(1 if self.sent else 0, len(self.tokens) - 1)], X.TOKEN, TOKACCT

    def simulate(self, tx):
        self.calls.append("simulate")
        return {"err": self.sim_err}

    def send(self, b64):
        self.sent.append(b64)
        return "SIG123"

    def status(self, sig):
        return {"confirmationStatus": self._status, "err": None}

    def block_height(self):
        return 10

    def call(self, method, params):
        self.calls.append(method)
        return {"value": {"blockhash": str(Hash.default())}}


@unittest.skipUnless(HAVE, "solders not installed")
class TestExecutorFlows(unittest.TestCase):
    def setUp(self):
        self.kp = Keypair()
        self.user = str(self.kp.pubkey())
        self.tx = swap_tx(self.kp)
        self.http_calls = []

    def http(self, tx=None, quote_extra=None, swap_extra=None):
        def fn(url, body=None, retries=2, timeout=15):
            self.http_calls.append(url)
            if "/quote" in url:
                return dict({"outAmount": "123456", "priceImpactPct": "0.0001", "routePlan": []}, **(quote_extra or {}))
            return dict({"swapTransaction": tx or self.tx, "lastValidBlockHeight": 1000}, **(swap_extra or {}))
        return fn

    def ex(self, cfg=None, env=None, sandbox=False, rpc=None, http=None, with_key=True):
        g = X.Guard(dict({"live": True}, **(cfg or {})), env=GOOD_ENV if env is None else env, kill="/nonexistent/KILL", sandbox=lambda: sandbox)
        return X.Executor(dict({"live": True}, **(cfg or {})), g, rpc=rpc or FakeRpc(), http_json=http or self.http(), keypair=self.kp if with_key else None,
                          pubkey=None if with_key else self.user, sleep=lambda s: None)

    def test_dry_run_builds_validates_simulates_and_sends_nothing(self):
        ex = self.ex(cfg={"live": False}, with_key=False)
        out = ex.buy(TOKMINT, 2.5, 75.0, 0, 0.0, live=False)
        self.assertEqual(out["mode"], "dry")
        self.assertIn("simulate", ex.rpc.calls)
        self.assertEqual(ex.rpc.sent, [])

    def test_live_refused_when_config_is_not_live_and_nothing_is_sent(self):
        ex = self.ex(cfg={"live": False})
        with self.assertRaises(X.Refused):
            ex.buy(TOKMINT, 2.5, 75.0, 0, 0.0, live=True)
        self.assertEqual(ex.rpc.sent, [])

    def test_live_refused_without_confirmation_or_in_a_sandbox(self):
        for kw in (dict(env={"BURNER_KEYPAIR_PATH": "/x"}), dict(sandbox=True)):
            ex = self.ex(**kw)
            with self.assertRaises(X.Refused):
                ex.buy(TOKMINT, 2.5, 75.0, 0, 0.0, live=True)
            self.assertEqual(ex.rpc.sent, [])

    def test_live_buy_signs_sends_and_measures_the_fill(self):
        ex = self.ex()
        out = ex.buy(TOKMINT, 2.5, 75.0, 0, 0.0, live=True)
        self.assertEqual(len(ex.rpc.sent), 1)
        self.assertEqual((out["signature"], out["tokens_raw"], out["lamports_spent"]), ("SIG123", 123456, 2_600_000))
        signed = VersionedTransaction.from_bytes(base64.b64decode(ex.rpc.sent[0]))
        self.assertNotEqual(str(signed.signatures[0]), "1" * 64)                        # actually signed

    def test_limits_are_checked_before_any_network_call(self):
        ex = self.ex()
        with self.assertRaises(X.Refused):
            ex.buy(TOKMINT, 50.0, 75.0, 0, 0.0, live=True)
        self.assertEqual((ex.rpc.sent, self.http_calls), ([], []))

    def test_wallet_that_is_too_rich_is_refused(self):
        ex = self.ex(rpc=FakeRpc(balances=(2_000_000_000_000,)))                       # 2,000 SOL
        with self.assertRaises(X.Refused) as c:
            ex.buy(TOKMINT, 2.5, 75.0, 0, 0.0, live=True)
        self.assertIn("burner", str(c.exception))
        self.assertEqual(ex.rpc.sent, [])

    def test_malicious_api_response_is_rejected_before_simulation_and_signing(self):
        evil = swap_tx(self.kp, extra=[ix(X.SYSTEM, struct.pack("<IQ", 2, 1_000_000), [(self.user, True, True), (rnd(), False, True)])])
        ex = self.ex(http=self.http(tx=evil))
        with self.assertRaises(X.Refused):
            ex.buy(TOKMINT, 2.5, 75.0, 0, 0.0, live=True)
        self.assertEqual(ex.rpc.sent, [])
        self.assertNotIn("simulate", ex.rpc.calls)

    def test_simulation_failures_stop_the_trade(self):
        for kw in (dict(rpc=FakeRpc(sim_err={"InstructionError": [0, "Custom"]})), dict(http=self.http(swap_extra={"simulationError": {"error": "boom"}}))):
            ex = self.ex(**kw)
            with self.assertRaises(X.Refused):
                ex.buy(TOKMINT, 2.5, 75.0, 0, 0.0, live=True)
            self.assertEqual(ex.rpc.sent, [])

    def test_high_price_impact_is_refused(self):
        ex = self.ex(http=self.http(quote_extra={"priceImpactPct": "0.2"}))
        with self.assertRaises(X.Refused) as c:
            ex.buy(TOKMINT, 2.5, 75.0, 0, 0.0, live=True)
        self.assertIn("price impact", str(c.exception))
        self.assertEqual(ex.rpc.sent, [])

    def test_expired_transaction_is_reported_not_assumed_filled(self):
        class Slow(FakeRpc):
            def status(self, sig):
                return None
            def block_height(self):
                return 10_000
        ex = self.ex(rpc=Slow())
        with self.assertRaises(RuntimeError) as c:
            ex.buy(TOKMINT, 2.5, 75.0, 0, 0.0, live=True)
        self.assertIn("expired", str(c.exception))

    def test_sell_works_with_kill_file_present_and_closes_the_account(self):
        kill = Path(tempfile.mkdtemp()) / "KILL"
        kill.write_text("x")
        g = X.Guard({"live": True}, env=GOOD_ENV, kill=kill, sandbox=lambda: False)
        rpc = FakeRpc(balances=(100_000_000, 150_000_000), tokens=(0,))
        sell_kp = self.kp
        http = lambda url, body=None, retries=2, timeout=15: ({"outAmount": "50000000", "priceImpactPct": "0", "routePlan": []} if "/quote" in url else {"swapTransaction": swap_tx(sell_kp, lamports=1_000_000), "lastValidBlockHeight": 1000})
        ex = X.Executor({"live": True}, g, rpc=rpc, http_json=http, keypair=self.kp, sleep=lambda s: None)
        out = ex.sell(TOKMINT, 123456, live=True)
        self.assertEqual(out["lamports_received"], 50_000_000)
        self.assertIsNotNone(out["close_signature"])
        self.assertEqual(len(rpc.sent), 2)                                              # the sell and the account closing


class TestNoSecretsInRepository(unittest.TestCase):
    def test_no_keypair_like_content_is_tracked(self):
        files = subprocess.run(["git", "ls-files"], cwd=X.REPO, capture_output=True, text=True).stdout.split()
        pat_array = re.compile(r"\[\s*(?:\d{1,3}\s*,\s*){63}\d{1,3}\s*\]")
        pat_b58 = re.compile(r"(?<![1-9A-HJ-NP-Za-km-z])[1-9A-HJ-NP-Za-km-z]{87,88}(?![1-9A-HJ-NP-Za-km-z])")
        for f in files:
            if f.endswith((".gz", ".png", ".db")):
                continue
            try:
                text = (X.REPO / f).read_text(errors="ignore")
            except OSError:
                continue
            self.assertIsNone(pat_array.search(text), f"64-byte array in {f}")
            self.assertIsNone(pat_b58.search(text), f"base58 secret-like string in {f}")


if __name__ == "__main__":
    unittest.main()
