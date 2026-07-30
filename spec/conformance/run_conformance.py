#!/usr/bin/env python3
"""CHP v1.0 conformance runner.

Tests any implementation, in any language, against the golden vectors.

    # the reference implementation must always pass
    python3 spec/conformance/run_conformance.py --adapter reference

    # a port in another language, via the line-JSON adapter protocol (§7.2)
    python3 spec/conformance/run_conformance.py --adapter-cmd "node adapters/my-port.js"

    # only one profile
    python3 spec/conformance/run_conformance.py --adapter reference --profile B

Exit status is 0 only when every selected vector passes, so this drops straight
into CI.

Adapter protocol (§7.2): the adapter reads one JSON request per line on stdin
and writes one JSON response per line on stdout, in order.

    -> {"op": "content_hash", "args": {"payload": {...}}}
    <- {"ok": true, "result": "9f86d0..."}
    <- {"ok": false, "error": "unsupported op"}

An adapter MAY answer `{"ok": false, "error": "unsupported"}` to any op it does
not implement; those vectors are reported SKIP, not FAIL, so a Profile-B-only
gate is not penalised for lacking deliberation ops.
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path
from typing import Any, Callable

HERE = Path(__file__).resolve().parent
VECTORS = HERE.parent / "golden-vectors"

sys.path.insert(0, str(HERE))


# ---------------------------------------------------------------- adapters


class ReferenceAdapter:
    """In-process adapter over chp_reference.py."""

    name = "reference"

    def __init__(self) -> None:
        import chp_reference as ref

        self.ref = ref

    def call(self, op: str, args: dict[str, Any]) -> Any:
        ref = self.ref
        if op == "canonical_json":
            return ref.canonical_json(args["payload"])
        if op == "content_hash":
            return ref.content_hash(args["payload"])
        if op == "chain_hash":
            return ref.chain_hash(args["prev_sig"], args["entry"])
        if op == "r0_gate":
            return ref.evaluate_r0_gate(**args)
        if op == "foundation_floor":
            return ref.foundation_floor(args["domain"])
        if op == "foundation_verdict":
            return ref.foundation_verdict(args["score"], args["domain"])
        if op == "phase_gate":
            return ref.evaluate_phase_gate(args["round"], ref.State(args["state"]))
        if op == "next_round":
            phase, rnd = ref.next_round(ref.Phase(args["phase"]), args["round"])
            return {"phase": phase.value, "round": rnd}
        if op == "model_parity":
            return ref.assess_model_parity(args["origin"], args["partner"])
        if op == "accuracy_guard":
            return ref.accuracy_guard(
                foundation_score=args["foundation_score"],
                domain=args["domain"],
                state=ref.State(args["state"]),
                structural_vulnerabilities=args.get("structural_vulnerabilities", []),
                blind_spots=args.get("blind_spots", []),
            )
        if op == "validate_payload_envelope":
            return ref.validate_payload_envelope(args["rendered"])
        if op == "payload_echo_confirmed":
            return ref.payload_echo_confirmed(args["route"], args["payload_id"], args["echo"])
        if op == "evaluate_gate":
            return ref.evaluate_gate(
                ref.ProposedAction(**args["action"]),
                _policy(ref, args["policy"]),
                committed_today=args.get("committed_today", 0.0),
            )
        if op == "approve_human":
            return ref.approve_human(
                ref.ProposedAction(**args["action"]),
                _policy(ref, args["policy"]),
                approver=args["approver"],
                committed_today=args.get("committed_today", 0.0),
            )
        raise Unsupported(op)


def _policy(ref, raw: dict[str, Any]):
    return ref.GatePolicy(
        version=raw.get("version", "1.0"),
        max_notional=raw["max_notional"],
        daily_cap=raw["daily_cap"],
        hitl_threshold=raw["hitl_threshold"],
        min_confidence=raw["min_confidence"],
        allowed_actions=tuple(raw.get("allowed_actions", ())),
        per_asset_limits=dict(raw.get("per_asset_limits", {})),
    )


class Unsupported(Exception):
    pass


class SubprocessAdapter:
    """Line-JSON adapter over an external process (§7.2)."""

    def __init__(self, cmd: str) -> None:
        self.name = cmd
        self.proc = subprocess.Popen(
            cmd, shell=True, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
            stderr=subprocess.PIPE, text=True, bufsize=1,
        )

    def call(self, op: str, args: dict[str, Any]) -> Any:
        assert self.proc.stdin and self.proc.stdout
        self.proc.stdin.write(json.dumps({"op": op, "args": args}) + "\n")
        self.proc.stdin.flush()
        line = self.proc.stdout.readline()
        if not line:
            err = (self.proc.stderr.read() if self.proc.stderr else "") or "adapter closed stdout"
            raise RuntimeError(f"adapter died during op {op!r}: {err.strip()[:400]}")
        resp = json.loads(line)
        if not resp.get("ok"):
            msg = str(resp.get("error", ""))
            if "unsupported" in msg.lower():
                raise Unsupported(op)
            raise AssertionError(msg or "adapter reported failure")
        return resp.get("result")

    def close(self) -> None:
        try:
            if self.proc.stdin:
                self.proc.stdin.close()
            self.proc.wait(timeout=5)
        except Exception:
            self.proc.kill()


# ---------------------------------------------------------------- runner


class Results:
    def __init__(self) -> None:
        self.passed = 0
        self.failed: list[tuple[str, Any, Any]] = []
        self.skipped: list[str] = []

    def check(self, name: str, expected: Any, call: Callable[[], Any]) -> None:
        try:
            actual = call()
        except Unsupported:
            self.skipped.append(name)
            return
        except Exception as exc:  # an adapter raising is a failure, not a skip
            self.failed.append((name, expected, f"<raised {type(exc).__name__}: {exc}>"))
            return
        if _eq(actual, expected):
            self.passed += 1
        else:
            self.failed.append((name, expected, actual))


def _eq(actual: Any, expected: Any) -> bool:
    """Compare, tolerating int/float and ignoring adapter-added extra keys.

    Extra keys are allowed so an implementation may carry its own metadata
    (decision ids, timestamps, logging fields) without failing conformance —
    but every key the spec names must match exactly.
    """
    if isinstance(expected, dict) and isinstance(actual, dict):
        return all(k in actual and _eq(actual[k], v) for k, v in expected.items())
    if isinstance(expected, list) and isinstance(actual, list):
        return len(expected) == len(actual) and all(_eq(a, e) for a, e in zip(actual, expected))
    if isinstance(expected, bool) or isinstance(actual, bool):
        return actual is expected
    if isinstance(expected, (int, float)) and isinstance(actual, (int, float)):
        return abs(float(actual) - float(expected)) < 1e-9
    return actual == expected


def load(name: str) -> dict:
    return json.loads((VECTORS / name).read_text(encoding="utf-8"))


def run_canonicalization(ad, r: Results) -> None:
    data = load("canonicalization.json")
    for v in data["vectors"]:
        r.check(f"canon/{v['name']}/json", v["canonical"],
                lambda v=v: ad.call("canonical_json", {"payload": v["input"]}))
        r.check(f"canon/{v['name']}/sha256", v["sha256"],
                lambda v=v: ad.call("content_hash", {"payload": v["input"]}))

    led = load("audit-ledger.json")
    for i, link in enumerate(led["chain"]):
        r.check(f"ledger/link-{i}", link["sig"],
                lambda link=link: ad.call("chain_hash",
                                          {"prev_sig": link["prev_sig"], "entry": link["entry"]}))


def run_profile_a(ad, r: Results) -> None:
    d = load("profile-a-deliberation.json")
    for c in d["r0_gate"]:
        r.check(f"A/r0/{c['name']}", c["expected"], lambda c=c: ad.call("r0_gate", c["input"]))
    for c in d["foundation_floors"]:
        r.check(f"A/floor/{c['domain'] or '<empty>'}", c["floor"],
                lambda c=c: ad.call("foundation_floor", {"domain": c["domain"]}))
    for c in d["foundation_verdict"]:
        r.check(f"A/foundation/{c['name']}", c["expected"],
                lambda c=c: ad.call("foundation_verdict", {"score": c["score"], "domain": c["domain"]}))
    for c in d["phase_gate"]:
        r.check(f"A/phase/{c['name']}", c["expected"],
                lambda c=c: ad.call("phase_gate", {"round": c["round"], "state": c["state"]}))
    for c in d["round_progression"]:
        r.check(f"A/round/{c['name']}", c["expected"],
                lambda c=c: ad.call("next_round", {"phase": c["phase"], "round": c["round"]}))
    for c in d["model_parity"]:
        r.check(f"A/parity/{c['name']}", c["expected"],
                lambda c=c: ad.call("model_parity", {"origin": c["origin"], "partner": c["partner"]}))
    for c in d["accuracy_guard"]:
        r.check(f"A/guard/{c['name']}", c["expected"], lambda c=c: ad.call("accuracy_guard", {
            "foundation_score": c["foundation_score"], "domain": c["domain"], "state": c["state"],
            "structural_vulnerabilities": c["structural_vulnerabilities"], "blind_spots": c["blind_spots"]}))

    env = d["payload_envelope"]
    r.check("A/envelope/valid", env["valid"],
            lambda: ad.call("validate_payload_envelope", {"rendered": env["rendered"]}))
    r.check("A/envelope/tampered-footer-rejected", env["tampered_footer_valid"],
            lambda: ad.call("validate_payload_envelope", {
                "rendered": env["rendered"].replace(
                    f"END_PAYLOAD [{env['route']}] [{env['payload_id']}]", "END_PAYLOAD [RX] [ZZZZZZ]")}))
    r.check("A/envelope/echo-confirmed", env["echo_confirmed"],
            lambda: ad.call("payload_echo_confirmed", {
                "route": env["route"], "payload_id": env["payload_id"],
                "echo": f"[{env['route']}] [{env['payload_id']}] CONFIRMED"}))
    r.check("A/envelope/echo-wrong-id-rejected", env["echo_wrong_id"],
            lambda: ad.call("payload_echo_confirmed", {
                "route": env["route"], "payload_id": env["payload_id"], "echo": "[RX] [ZZZZZZ] CONFIRMED"}))


def run_profile_b(ad, r: Results) -> None:
    d = load("profile-b-capital-gate.json")
    policy = d["policy"]
    for c in d["evaluate"]:
        r.check(f"B/evaluate/{c['name']}", c["expected"], lambda c=c: ad.call("evaluate_gate", {
            "action": c["action"], "policy": policy, "committed_today": c["committed_today"]}))
    for c in d["approve_human"]:
        r.check(f"B/approve/{c['name']}", c["expected"], lambda c=c: ad.call("approve_human", {
            "action": c["action"], "policy": policy, "approver": c["approver"],
            "committed_today": c["committed_today"]}))


def main() -> int:
    ap = argparse.ArgumentParser(description="CHP v1.0 conformance runner")
    g = ap.add_mutually_exclusive_group(required=True)
    g.add_argument("--adapter", choices=["reference"], help="built-in in-process adapter")
    g.add_argument("--adapter-cmd", help="external adapter command (line-JSON protocol)")
    ap.add_argument("--profile", choices=["A", "B", "both"], default="both")
    ap.add_argument("--quiet", action="store_true", help="only print the summary")
    args = ap.parse_args()

    ad = ReferenceAdapter() if args.adapter else SubprocessAdapter(args.adapter_cmd)
    r = Results()
    try:
        run_canonicalization(ad, r)
        if args.profile in ("A", "both"):
            run_profile_a(ad, r)
        if args.profile in ("B", "both"):
            run_profile_b(ad, r)
    finally:
        if isinstance(ad, SubprocessAdapter):
            ad.close()

    total = r.passed + len(r.failed)
    print(f"\nCHP v1.0 conformance — adapter: {ad.name}")
    print(f"  passed  {r.passed}/{total}")
    if r.skipped:
        print(f"  skipped {len(r.skipped)} (unsupported ops)")
        if not args.quiet:
            for s in r.skipped:
                print(f"            - {s}")
    if r.failed:
        print(f"  FAILED  {len(r.failed)}")
        for name, expected, actual in r.failed:
            print(f"\n  ✗ {name}")
            print(f"      expected: {json.dumps(expected, ensure_ascii=False)}")
            print(f"      actual:   {json.dumps(actual, ensure_ascii=False, default=str)}")
        return 1
    print("  result  CONFORMANT")
    return 0


if __name__ == "__main__":
    sys.exit(main())
