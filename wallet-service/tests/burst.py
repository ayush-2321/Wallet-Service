#!/usr/bin/env python3
"""One-command burst harness for the wallet service.

Runs the three probes the exercise grades and ASSERTS the invariants:
  1. Concurrent get-or-create  -> exactly one wallet for a brand-new user
  2. Idempotent retry storm     -> one debit/credit, identical responses
  3. Conservation under load    -> total balance unchanged, nothing negative

Stdlib only (urllib + threads), so it runs anywhere Python 3 is present and
works against a local container OR the deployed public URL.

    python3 tests/burst.py                      # defaults to http://localhost:8000
    python3 tests/burst.py https://your-app.onrender.com
"""
import json
import sys
import urllib.error
import urllib.request
import uuid
from concurrent.futures import ThreadPoolExecutor

BASE = (sys.argv[1] if len(sys.argv) > 1 else "http://localhost:8000").rstrip("/")
RUN = uuid.uuid4().hex[:8]  # unique per run so re-runs never collide on keys/users
_failures = []


def call(method, path, token=None, body=None, headers=None):
    data = json.dumps(body).encode() if body is not None else None
    hdrs = {"Content-Type": "application/json"}
    if token:
        hdrs["Authorization"] = f"Bearer {token}"
    if headers:
        hdrs.update(headers)
    req = urllib.request.Request(BASE + path, data=data, headers=hdrs, method=method)
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            return resp.status, json.loads(resp.read() or b"{}")
    except urllib.error.HTTPError as e:
        try:
            payload = json.loads(e.read() or b"{}")
        except Exception:
            payload = {}
        return e.code, payload


def fan_out(n, fn):
    with ThreadPoolExecutor(max_workers=min(n, 64)) as pool:
        return list(pool.map(lambda i: fn(i), range(n)))


def check(name, ok, detail=""):
    print(f"  [{'PASS' if ok else 'FAIL'}] {name}" + (f" -- {detail}" if detail else ""))
    if not ok:
        _failures.append(name)


def make_wallet(label):
    token = f"{label}-{RUN}"
    status, body = call("POST", "/wallets", token=token)
    return token, body.get("wallet_id"), status


def balance(token, wallet_id):
    _, body = call("GET", f"/wallets/{wallet_id}", token=token)
    return body.get("balance_paise")


# ---------------------------------------------------------------- Probe 1
def probe_get_or_create(n=50):
    print(f"\nProbe 1: {n} concurrent POST /wallets for one brand-new user")
    token = f"new-user-{RUN}"
    results = fan_out(n, lambda i: call("POST", "/wallets", token=token))
    ids = {b.get("wallet_id") for _, b in results}
    codes = {s for s, _ in results}
    check("all requests succeeded (200)", codes == {200}, f"codes={codes}")
    check("exactly one wallet created", len(ids) == 1, f"distinct wallet_ids={len(ids)}")


# ---------------------------------------------------------------- Probe 2
def probe_idempotent_storm(k=50, amount=1000):
    print(f"\nProbe 2: {k} concurrent identical transfers (same idempotency key)")
    tok_a, wa, _ = make_wallet("idem-a")
    tok_b, wb, _ = make_wallet("idem-b")
    call("POST", f"/wallets/{wa}/deposit", token=tok_a, body={"amount_paise": amount})
    key = f"idem-key-{RUN}"
    body = {"from": wa, "to": wb, "amount_paise": amount}

    results = fan_out(k, lambda i: call("POST", "/transfers", token=tok_a, body=body, headers={"Idempotency-Key": key}))
    ok_codes = all(s == 200 for s, _ in results)
    ids = {b.get("transfer_id") for _, b in results}
    statuses = {b.get("status") for _, b in results}
    check("all responses 200", ok_codes)
    check("all responses share one transfer_id", len(ids) == 1, f"distinct ids={len(ids)}")
    check("all responses report SUCCESS", statuses == {"SUCCESS"}, f"statuses={statuses}")
    check("source debited exactly once", balance(tok_a, wa) == 0, f"A={balance(tok_a, wa)}")
    check("destination credited exactly once", balance(tok_b, wb) == amount, f"B={balance(tok_b, wb)}")


# ---------------------------------------------------------------- Probe 3
def probe_conservation(wallets=5, seed=100_000, transfers=200, amount=500):
    print(f"\nProbe 3: {transfers} concurrent transfers among {wallets} wallets (incl. A<->B both ways)")
    accts = [make_wallet(f"cons-{i}") for i in range(wallets)]
    for token, wid, _ in accts:
        call("POST", f"/wallets/{wid}/deposit", token=token, body={"amount_paise": seed})
    total_before = sum(balance(t, w) for t, w, _ in accts)

    def one(i):
        src = i % wallets
        dst = (i + 1 + (i % (wallets - 1))) % wallets  # varied pairs, both directions
        if dst == src:
            dst = (src + 1) % wallets
        tok, wid, _ = accts[src]
        _, dwid, _ = accts[dst]
        return call("POST", "/transfers", token=tok,
                    body={"from": wid, "to": dwid, "amount_paise": amount},
                    headers={"Idempotency-Key": f"cons-{RUN}-{i}"})

    fan_out(transfers, one)
    finals = [balance(t, w) for t, w, _ in accts]
    total_after = sum(finals)
    check("conservation: total balance unchanged", total_after == total_before, f"{total_before} -> {total_after}")
    check("no wallet went negative", all(b >= 0 for b in finals), f"balances={finals}")


if __name__ == "__main__":
    print(f"Target: {BASE}  (run id {RUN})")
    code, _ = call("GET", "/health")
    if code != 200:
        print(f"  service not reachable at {BASE} (health -> {code})")
        sys.exit(2)
    probe_get_or_create()
    probe_idempotent_storm()
    probe_conservation()
    print()
    if _failures:
        print(f"RESULT: FAIL ({len(_failures)} check(s) failed: {', '.join(_failures)})")
        sys.exit(1)
    print("RESULT: PASS -- all invariants held")
