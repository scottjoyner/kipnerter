#!/usr/bin/env python3
"""Preflight before failure: cross-image, research-only compatibility rehearsal.

Never authorizes production rollback. Uses pinned existing research images only.
"""
from __future__ import annotations

import argparse
import json
import re
import secrets
import subprocess
import sys
import time

try:
    from scripts.portal_legacy_isolated_candidate_smoke import RESEARCH, runner
    from scripts.portal_legacy_research_failure_recovery import (
        _cleanup, _result_for, _stopped,
    )
except ModuleNotFoundError as exc:
    if exc.name != "scripts":
        raise
    from portal_legacy_isolated_candidate_smoke import RESEARCH, runner
    from portal_legacy_research_failure_recovery import _cleanup, _result_for, _stopped


# The positive control is only synthetic HTTP mechanics. Historic candidate
# downgrades MUST be preflighted and will HOLD if routes disappear.
PAIRS = {
    ("compat-031", "synthetic-loopback"),
    ("compat-031", "ios17-research"),
    ("compat-031", "turns-research"),
    ("compat-031", "recovery-research"),
}
HEX = re.compile(r"[a-f0-9]{12}\Z")


def rehearsal(upgrade_role, rollback_role, *, call=runner,
              pauses=time.sleep, nonces=None):
    if (upgrade_role, rollback_role) not in PAIRS:
        raise ValueError("unapproved research-only version pair")
    upgrade_image, rollback_image = RESEARCH[upgrade_role], RESEARCH[rollback_role]
    if upgrade_image == rollback_image:
        raise ValueError("cross-image gate requires distinct immutable images")
    if nonces is None:
        nonces = tuple(secrets.token_hex(6) for _ in range(3))
    if (not isinstance(nonces, (list, tuple)) or len(nonces) != 3 or
            len(set(nonces)) != 3 or
            any(not isinstance(x, str) or not HEX.fullmatch(x) for x in nonces)):
        raise ValueError("unapproved disposable container identities")
    for image in (upgrade_image, rollback_image):
        if call(["docker", "image", "inspect", "--format", "{{.Id}}", image]) != image:
            raise ValueError("required pinned local image unavailable")
    names = ["kp-legacy-isolated-" + x for x in nonces]
    generated = []
    cleanup_ok = False
    qualified_fallback = False
    qualified_upgrade = False
    failure_injected = False
    recovered = False
    try:
        # Critical sequencing: rollback target must satisfy exact current
        # auth/route contract BEFORE any upgrade candidate is killed.
        generated.append(names[0])
        previous_id = _result_for(names[0], rollback_image,
                                  call=call, pauses=pauses)
        _cleanup(names[0], call=call)
        qualified_fallback = True

        generated.append(names[1])
        upgrade_id = _result_for(names[1], upgrade_image,
                                 call=call, pauses=pauses)
        binding = call(["docker", "inspect", "--format",
                        "{{.Id}}|{{.Image}}|{{.Name}}|{{.State.Running}}",
                        upgrade_id], timeout=8)
        if binding != "|".join([upgrade_id, upgrade_image, "/" + names[1], "true"]):
            raise ValueError("candidate identity changed before failure injection")
        qualified_upgrade = True
        if call(["docker", "kill", "--signal", "SIGKILL", upgrade_id],
                timeout=12) != upgrade_id:
            raise ValueError("SIGKILL target was not exact disposable container")
        _stopped(names[1], call=call, pauses=pauses)
        failure_injected = True

        generated.append(names[2])
        restarted_id = _result_for(names[2], rollback_image,
                                   call=call, pauses=pauses)
        if restarted_id in (previous_id, upgrade_id):
            raise ValueError("fresh fallback container identity not observed")
        recovered = True
    finally:
        cleanup_results = []
        for name in reversed(generated):
            try:
                _cleanup(name, call=call)
                cleanup_results.append(True)
            except (OSError, ValueError, subprocess.SubprocessError):
                cleanup_results.append(False)
        cleanup_ok = len(cleanup_results) == len(generated) and all(cleanup_results)
        if not cleanup_ok:
            raise ValueError("disposable container cleanup incomplete")
    if not all((qualified_fallback, qualified_upgrade,
                failure_injected, recovered, cleanup_ok)):
        raise ValueError("cross-image research recovery incomplete")
    return {
        "status": "SYNTHETIC_CROSS_IMAGE_MECHANICS_PASS_NOT_ROLLBACK",
        "upgrade_role": upgrade_role,
        "fallback_role": rollback_role,
        "distinct_pinned_images_verified": True,
        "rollback_candidate_prequalified_before_any_injection": True,
        "upgrade_candidate_health_and_auth_verified": True,
        "upgrade_disposable_sigkill_observed": True,
        "fallback_fresh_container_id_verified": True,
        "fallback_health_and_auth_reverified": True,
        "all_temporary_containers_cleaned": True,
        "synthetic_http_fallback_not_real_api": rollback_role == "synthetic-loopback",
        "original_historical_production_image_recovered": False,
        "original_production_web_tested": False,
        "operational_equivalence_verified": False,
        "production_data_rollback_verified": False,
        "independent_custody_verified": False,
        "real_chat_execution_verified": False,
        "production_modified": False,
        "safe_to_cutover": False,
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--upgrade-role", choices=tuple(sorted({a for a, _ in PAIRS})), required=True)
    parser.add_argument("--fallback-role", choices=tuple(sorted({b for _, b in PAIRS})), required=True)
    opts = parser.parse_args()
    try:
        report = rehearsal(opts.upgrade_role, opts.fallback_role)
    except (OSError, ValueError, UnicodeError, subprocess.SubprocessError):
        report = {
            "status": "HOLD",
            "rollback_candidate_prequalified_before_any_injection": False,
            "operational_equivalence_verified": False,
            "safe_to_cutover": False,
        }
        print(json.dumps(report, sort_keys=True))
        return 2
    print(json.dumps(report, sort_keys=True))
    return 0


if __name__ == "__main__":
    sys.exit(main())
