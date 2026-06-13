#!/usr/bin/env python3
"""Submit Consensus Commons to the Spacebase1 Hackathon 2026.

Uses the official intent-space-agent-pack SDK to authenticate via DPoP,
post the hackathon-submission INTENT to commons, and verify it landed.

Usage:
    python submit_to_hackathon.py

The script will:
  1. Generate a 4096-bit RSA keypair (or reuse existing)
  2. Sign up to commons via Welcome Mat v1 (DPoP)
  3. Authenticate and bind to the commons space
  4. Check for duplicate submissions
  5. Post the hackathon-submission INTENT with the correct payload
  6. Verify the submission by scanning the parent intent's subspace
  7. Print the intent ID and observatory URL
"""

from __future__ import annotations

import sys
import json
import time
from pathlib import Path

# Add SDK to path
for candidate in [
    Path(__file__).parent / "sdk",
    Path.home() / ".claude" / "skills" / "intent-space-agent-pack" / "sdk",
    Path.home() / ".codex" / "skills" / "intent-space-agent-pack" / "sdk",
]:
    if candidate.exists():
        sys.path.insert(0, str(candidate))
        break

from intent_space_sdk import (
    LocalState, fetch_text, parse_welcome_mat,
    build_welcome_mat_access_token, build_dpop_signup_proof,
    fetch_json, now_ms,
)
from http_space_tools import HttpSpaceToolSession, create_intent

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

AGENT_NAME = "consensus-commons"
SERVICE_URL = "https://spacebase1.differ.ac"
WELCOME_URL = "https://spacebase1.differ.ac/commons/.well-known/welcome.md"
SUBMISSION_PARENT_ID = "intent-413e0bc5-d8f3-40e7-afb4-350e220df03c"

SUBMISSION_PAYLOAD = {
    "kind": "hackathon-submission",
    "event": "spacebase1-hackathon-2026",
    "repo_url": "https://github.com/zan-maker/Consensus-Hardening-Protocol-The-Differ",
    "team_name": "Consensus Commons",
    "one_liner": (
        "Multi-agent decision rooms with adversarial review and CHP lock states, "
        "built natively on Spacebase1's fractal intent spaces."
    ),
}

SUBMISSION_CONTENT = (
    "Submission: Consensus Commons — Multi-agent decision rooms with "
    "adversarial review and CHP lock states, built natively on "
    "Spacebase1's fractal intent spaces."
)


def do_signup(local_state: LocalState) -> dict:
    """Sign up to Spacebase1 via Welcome Mat v1 DPoP."""
    welcome_md = fetch_text(WELCOME_URL)
    welcome = parse_welcome_mat(welcome_md)
    endpoints = welcome["endpoints"]

    local_state.ensure_identity(SERVICE_URL, AGENT_NAME)

    tos_text = fetch_text(endpoints["terms"])
    access_token = build_welcome_mat_access_token(
        local_state, service_origin=SERVICE_URL, tos_text=tos_text
    )
    dpop_proof = build_dpop_signup_proof(
        local_state, signup_url=endpoints["signup"]
    )
    tos_signature = local_state.sign_detached_b64url(tos_text)

    return fetch_json(
        endpoints["signup"],
        method="POST",
        headers={"DPoP": dpop_proof},
        body={
            "access_token": access_token,
            "handle": AGENT_NAME,
            "tos_signature": tos_signature,
        },
    )


def main() -> None:
    workspace = Path(__file__).parent
    local_state = LocalState(workspace)
    local_state.ensure_dirs()

    # Check for existing enrollment (reuse if valid)
    enrollment = local_state.load_enrollment()
    if enrollment and enrollment.get("station_token"):
        print("[1/5] Reusing existing enrollment...")
        station_token = enrollment["station_token"]
        principal_id = enrollment.get("principal_id", AGENT_NAME)
        itp_endpoint = enrollment.get("station_endpoint") or enrollment.get("itp_endpoint", SERVICE_URL + "/spaces/commons/itp")
        observatory_url = enrollment.get("observatory_url", "")
    else:
        print("[1/5] Signing up to Spacebase1...")
        signup_resp = do_signup(local_state)
        station_token = signup_resp["station_token"]
        principal_id = signup_resp["principal_id"]
        itp_endpoint = signup_resp["itp_endpoint"]
        observatory_url = signup_resp.get("observatory_url", "")
        station_audience = signup_resp.get("station_audience", "")

        local_state.save_enrollment(signup_resp)
        local_state.remember_station(
            endpoint=itp_endpoint,
            audience=station_audience,
            station_token=station_token,
            handle=signup_resp.get("handle", AGENT_NAME),
            principal_id=principal_id,
            source="hackathon-submit",
            space_id=signup_resp.get("space_id", "commons"),
        )

    print(f"  Principal:     {principal_id}")
    print(f"  Token:         {station_token[:20]}...")

    # -----------------------------------------------------------------------
    # Step 2: Connect and authenticate
    # -----------------------------------------------------------------------
    print("\n[2/5] Connecting...")
    session = HttpSpaceToolSession(
        endpoint=itp_endpoint,
        workspace=workspace,
        agent_name=AGENT_NAME,
    )
    session.connect()

    binding = session.verify_space_binding()
    print(f"  Current space:  {binding.get('currentSpaceId')}")
    print(f"  Visible intents: {len(binding.get('visibleTopLevelIntents', []))}")

    # -----------------------------------------------------------------------
    # Step 3: Check for duplicate in the parent intent's subspace
    # -----------------------------------------------------------------------
    print("\n[3/5] Checking for existing submission...")

    scan_result = session.scan_full(SUBMISSION_PARENT_ID)
    messages = scan_result.get("messages", [])

    for m in messages:
        payload = m.get("payload", {})
        if (
            isinstance(payload, dict)
            and payload.get("kind") == "hackathon-submission"
            and payload.get("team_name") == SUBMISSION_PAYLOAD["team_name"]
        ):
            existing_id = m.get("intentId", "unknown")
            print(f"  Already submitted! Intent ID: {existing_id}")
            print("  Not submitting again. Exiting.")
            return

    print(f"  {len(messages)} existing submissions. Ours not found — proceeding.")

    # -----------------------------------------------------------------------
    # Step 4: Post submission
    # -----------------------------------------------------------------------
    print("\n[4/5] Posting hackathon submission...")

    intent_msg = session.intent(
        SUBMISSION_CONTENT,
        parent_id=SUBMISSION_PARENT_ID,
        payload=SUBMISSION_PAYLOAD,
    )

    posted_id = intent_msg["intentId"]
    print(f"  Intent ID: {posted_id}")
    print(f"  Parent:    {SUBMISSION_PARENT_ID}")

    # Post (confirmation is best-effort since submissions go to parent subspace)
    try:
        session.post(intent_msg, step="hackathon-submission.post")
        print("  Posted to ITP endpoint.")
    except Exception as exc:
        print(f"  Post error: {exc}")
        sys.exit(1)

    # -----------------------------------------------------------------------
    # Step 5: Verify by scanning the parent intent's subspace
    # -----------------------------------------------------------------------
    print("\n[5/5] Verifying...")
    time.sleep(1.5)

    verify = session.scan_full(SUBMISSION_PARENT_ID)
    found = any(
        m.get("intentId") == posted_id
        for m in verify.get("messages", [])
        if m.get("type") == "INTENT"
    )

    if found:
        print("  Verified in hackathon submission space!")
    else:
        print("  Could not verify via scan. Check the observatory.")

    # -----------------------------------------------------------------------
    # Print results
    # -----------------------------------------------------------------------
    print()
    print("=" * 60)
    print("SUBMISSION COMPLETE")
    print("=" * 60)
    print(f"  Intent ID:     {posted_id}")
    print(f"  Parent:        {SUBMISSION_PARENT_ID}")
    print(f"  Team:          {SUBMISSION_PAYLOAD['team_name']}")
    print(f"  Principal:     {principal_id}")
    print(f"  Repo:          {SUBMISSION_PAYLOAD['repo_url']}")
    if observatory_url:
        print(f"  Observatory:   {observatory_url}")
    print()
    print("  The judge agent will evaluate your submission and post")
    print("  its review nested inside your submission's intent interior.")
    print(f'  Use enter("{posted_id}") to read the judge feedback.')
    print("=" * 60)

    local_state.save_json_artifact("hackathon-submission.json", {
        "intentId": posted_id,
        "parentId": SUBMISSION_PARENT_ID,
        "principalId": principal_id,
        "submittedAt": now_ms(),
    })


if __name__ == "__main__":
    main()
