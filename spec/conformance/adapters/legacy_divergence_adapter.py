#!/usr/bin/env python3
"""An adapter that reproduces the real non-conformant behaviours found in the
shipped ports, so the conformance suite can be shown to have teeth.

This is NOT a port under test. It is a fixture: each behaviour here was read out
of a real file in the portfolio (cited per-op below), and the runner MUST fail
on it. If this adapter ever passes, the suite has stopped detecting regressions.

    python3 spec/conformance/run_conformance.py \
        --adapter-cmd "python3 spec/conformance/adapters/legacy_divergence_adapter.py"

Expected: FAILED, with the divergences listed in ../../DIVERGENCES.md.
"""
from __future__ import annotations

import hashlib
import json
import sys
from datetime import datetime, timezone

# D-B1: cognitrader-bsc/src/chp/gate.ts finalize() — JSON.stringify with
# insertion order, no key sorting.
def unsorted_hash(payload: dict) -> str:
    return hashlib.sha256(
        json.dumps(payload, separators=(",", ":")).encode("utf-8")
    ).hexdigest()


# D-B4: cognitrader-bsc rolling 24h window anchored to process start, rather
# than the UTC calendar day.
_WINDOW_START = datetime.now(timezone.utc)


def handle(op: str, args: dict):
    # D-B1 — unsorted canonical form.
    if op == "canonical_json":
        return json.dumps(args["payload"], separators=(",", ":"))
    if op == "content_hash":
        return unsorted_hash(args["payload"])
    if op == "chain_hash":
        return unsorted_hash({"prev_sig": args["prev_sig"], "entry": args["entry"]})

    # D-A1: foundation.py hardcodes >= 70 for every domain, so the documented
    # finance floor of 100 is never enforced.
    if op == "foundation_floor":
        return 70
    if op == "foundation_verdict":
        return "PASS" if args["score"] >= 70 else "REFRAME"

    if op == "evaluate_gate":
        return legacy_gate(args)
    if op == "approve_human":
        return legacy_approve(args)

    raise Unsupported()


class Unsupported(Exception):
    pass


def legacy_gate(args: dict) -> dict:
    """cognitrader/courtvision gate behaviour, with their divergences intact."""
    a, p = args["action"], args["policy"]
    committed = args.get("committed_today", 0.0)
    notional = a["notional"]
    claims = []

    def add(rule, passed, detail):
        claims.append({"rule": rule, "passed": passed, "detail": detail})
        return passed

    ok = True
    ok &= add("sane-notional", notional > 0, f"notional={notional}")
    if p.get("allowed_actions"):
        ok &= add("allowed-action", a["action"] in p["allowed_actions"], f"action {a['action']}")
    cap = p.get("per_asset_limits", {}).get(a["asset"], p["max_notional"])
    ok &= add("per-asset-cap", notional <= cap, f"{a['asset']} notional {notional} vs cap {cap}")
    ok &= add("max-notional", notional <= p["max_notional"], f"{notional} vs max {p['max_notional']}")
    ok &= add("daily-cap", committed + notional <= p["daily_cap"],
              f"projected {committed + notional} vs daily cap {p['daily_cap']}")
    if a.get("confidence") is not None:
        ok &= add("min-confidence", a["confidence"] >= p["min_confidence"],
                  f"confidence {a['confidence']} vs min {p['min_confidence']}")

    # D-B2: courtvision uses lowercase state values on the wire.
    if not ok:
        return _res("blocked", claims, False, False, notional, committed_delta=0.0)
    if notional >= p["hitl_threshold"]:
        return _res("hitl_required", claims, False, True, notional, committed_delta=0.0)
    return _res("locked", claims, True, False, notional, committed_delta=notional)


def legacy_approve(args: dict) -> dict:
    """D-B5: cognitrader approveHuman() re-checks only the notional caps, so a
    human can approve an action that evaluate() would have blocked for low
    confidence or a disallowed action type."""
    a, p = args["action"], args["policy"]
    committed = args.get("committed_today", 0.0)
    notional = a["notional"]
    if notional > p["max_notional"] or committed + notional > p["daily_cap"]:
        return _res("blocked", [{"rule": "post-approval-recheck", "passed": False,
                                 "detail": "exceeds hard caps even with approval"}],
                    False, False, notional, committed_delta=0.0)
    # Confidence and allowlist are NOT re-checked here — that is the bug.
    return _res("locked", [{"rule": "human-approval", "passed": True,
                            "detail": f"approved by {args['approver']}"}],
                True, False, notional, committed_delta=notional)


def _res(state, claims, allowed, requires_human, notional, committed_delta):
    return {
        "state": state,
        "allowed": allowed,
        "requires_human": requires_human,
        "reason": "legacy",
        "claims": claims,
        # D-B3: hashes a different field set, including wall-clock time, so no
        # two runs of the same logical decision agree.
        "content_hash": unsorted_hash({
            "state": state, "notional": notional,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }),
        "committed_delta": committed_delta,
    }


def main() -> None:
    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        req = json.loads(line)
        try:
            result = handle(req["op"], req.get("args", {}))
            out = {"ok": True, "result": result}
        except Unsupported:
            out = {"ok": False, "error": "unsupported op"}
        except Exception as exc:  # noqa: BLE001
            out = {"ok": False, "error": f"{type(exc).__name__}: {exc}"}
        sys.stdout.write(json.dumps(out) + "\n")
        sys.stdout.flush()


if __name__ == "__main__":
    main()
