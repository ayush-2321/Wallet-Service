#!/usr/bin/env bash
# Bash + curl burst harness (same three probes as burst.py). Needs: curl, jq.
#   ./tests/burst.sh                       # defaults to http://localhost:8000
#   ./tests/burst.sh https://your-app.onrender.com
set -euo pipefail

BASE="${1:-http://localhost:8000}"; BASE="${BASE%/}"
RUN="$(uuidgen | tr 'A-Z' 'a-z' | cut -c1-8)"
TMP="$(mktemp -d)"; trap 'rm -rf "$TMP"' EXIT
FAIL=0

pass() { echo "  [PASS] $1"; }
fail() { echo "  [FAIL] $1 -- $2"; FAIL=1; }

CURL="curl -s -m 60"   # 60s per-request timeout so a slow free-tier box can't hang the run
post_wallet() { $CURL -X POST "$BASE/wallets" -H "Authorization: Bearer $1"; }
deposit()     { $CURL -X POST "$BASE/wallets/$2/deposit" -H "Authorization: Bearer $1" -H 'Content-Type: application/json' -d "{\"amount_paise\":$3}"; }
get_balance() { $CURL "$BASE/wallets/$2" -H "Authorization: Bearer $1" | jq -r .balance_paise; }
transfer() { # token from to amount key -> writes JSON to stdout
  $CURL -X POST "$BASE/transfers" -H "Authorization: Bearer $1" -H "Idempotency-Key: $5" \
       -H 'Content-Type: application/json' -d "{\"from\":\"$2\",\"to\":\"$3\",\"amount_paise\":$4}"
}

echo "Target: $BASE  (run id $RUN)"
[ "$(curl -s -o /dev/null -w '%{http_code}' "$BASE/health")" = "200" ] || { echo "  service not reachable"; exit 2; }

# ---------------------------------------------------------- Probe 1
N=50
echo; echo "Probe 1: $N concurrent POST /wallets for one brand-new user"
tok="newuser-$RUN"
for i in $(seq 1 $N); do post_wallet "$tok" > "$TMP/w.$i" & done; wait
distinct=$(cat "$TMP"/w.* | jq -r .wallet_id | sort -u | wc -l | tr -d ' ')
[ "$distinct" = "1" ] && pass "exactly one wallet created" || fail "one wallet" "distinct=$distinct"

# ---------------------------------------------------------- Probe 2
K=50; AMT=1000
echo; echo "Probe 2: $K concurrent identical transfers (same idempotency key)"
ta="idemA-$RUN"; tb="idemB-$RUN"
wa=$(post_wallet "$ta" | jq -r .wallet_id); wb=$(post_wallet "$tb" | jq -r .wallet_id)
deposit "$ta" "$wa" "$AMT" >/dev/null
key="idemkey-$RUN"
for i in $(seq 1 $K); do transfer "$ta" "$wa" "$wb" "$AMT" "$key" > "$TMP/t.$i" & done; wait
tids=$(cat "$TMP"/t.* | jq -r .transfer_id | sort -u | wc -l | tr -d ' ')
[ "$tids" = "1" ] && pass "all responses share one transfer_id" || fail "one transfer_id" "distinct=$tids"
[ "$(get_balance "$ta" "$wa")" = "0" ]   && pass "source debited exactly once"      || fail "debit once" "A=$(get_balance "$ta" "$wa")"
[ "$(get_balance "$tb" "$wb")" = "$AMT" ] && pass "destination credited exactly once" || fail "credit once" "B=$(get_balance "$tb" "$wb")"

# ---------------------------------------------------------- Probe 3
W=5; SEED=100000; XFERS=60; TAMT=500   # XFERS modest so it finishes on free-tier hosts
echo; echo "Probe 3: $XFERS concurrent transfers among $W wallets (both directions)"
tokens=(); ids=()
for i in $(seq 0 $((W-1))); do
  t="cons-$i-$RUN"; id=$(post_wallet "$t" | jq -r .wallet_id)
  deposit "$t" "$id" "$SEED" >/dev/null
  tokens+=("$t"); ids+=("$id")
done
before=$((W*SEED))
for i in $(seq 0 $((XFERS-1))); do
  s=$((i % W)); d=$(((i+1) % W))
  transfer "${tokens[$s]}" "${ids[$s]}" "${ids[$d]}" "$TAMT" "cons-$RUN-$i" >/dev/null &
  [ $((i % 16)) -eq 15 ] && wait   # cap in-flight fan-out (gentle on free tier)
done; wait
after=0; neg=0
for i in $(seq 0 $((W-1))); do
  b=$(get_balance "${tokens[$i]}" "${ids[$i]}"); after=$((after+b))
  [ "$b" -lt 0 ] && neg=1
done
[ "$after" = "$before" ] && pass "conservation: total unchanged ($before)" || fail "conservation" "$before -> $after"
[ "$neg" = "0" ] && pass "no wallet went negative" || fail "no overdraft" "a balance was negative"

echo
[ "$FAIL" = "0" ] && { echo "RESULT: PASS -- all invariants held"; exit 0; } || { echo "RESULT: FAIL"; exit 1; }
