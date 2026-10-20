#!/usr/bin/env python3
"""Read-only-targeted, ephemeral failure/recovery test of a pinned research image.

This is a same-image restart-after-SIGKILL canary, NOT historical production
rollback, restored state, or independent custody. Never opens production hosts.
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
    from scripts.portal_legacy_isolated_candidate_smoke import (
        RESEARCH, classify_probe, commands, runner, safety_inspect,
    )
except ModuleNotFoundError as exc:
    if exc.name != "scripts":
        raise
    from portal_legacy_isolated_candidate_smoke import (
        RESEARCH, classify_probe, commands, runner, safety_inspect,
    )

FULL_ID = re.compile(r"[a-f0-9]{64}\Z")
NAME = re.compile(r"kp-legacy-isolated-[a-f0-9]{12}\Z")


def _result_for(name, image, *, call, pauses):
    start, inspect, probe, remove = commands(
        name, image, synthetic=image == RESEARCH["synthetic-loopback"])
    begun = False
    ident = None
    try:
        begun = True  # a timed-out docker run may have created this exact name
        ident = call(start, timeout=30)
        if not FULL_ID.fullmatch(ident):
            raise ValueError("invalid disposable container ID")
        safety_inspect(call(inspect, timeout=8), image)
        # Bind the potentially destructive action to the exact container ID,
        # image ID, name and running state after the full isolation readback.
        binding = call(["docker", "inspect", "--format",
                        "{{.Id}}|{{.Image}}|{{.Name}}|{{.State.Running}}",
                        name], timeout=8)
        if binding != "|".join([ident, image, "/" + name, "true"]):
            raise ValueError("disposable container identity mismatch")
        healthy = False
        for idx in range(20):
            try:
                classify_probe(call(probe, timeout=9))
                healthy = True
                break
            except (ValueError, subprocess.SubprocessError, UnicodeError):
                if idx != 19:
                    pauses(0.4)
        if not healthy:
            raise ValueError("isolated candidate startup/auth contract failed")
        return ident
    except BaseException:
        if begun:
            _cleanup(name, call=call)
        raise


def _stopped(name, *, call, pauses):
    for idx in range(12):
        status = call(["docker", "ps", "--all",
                       "--filter", "name=^/" + name + "$",
                       "--format", "{{.Names}}"], timeout=8)
        if not status:
            return True
        if idx != 11:
            pauses(0.25)
    raise ValueError("injected container did not disappear")


def _cleanup(name, *, call):
    if not NAME.fullmatch(name):
        raise ValueError("unsafe disposable cleanup target")
    try:
        call(["docker", "rm", "--force", name], timeout=12)
    except (ValueError, subprocess.SubprocessError):
        # --rm auto-deletes a deliberately killed container. Verify below.
        pass
    result = call(["docker", "ps", "--all",
                   "--filter", "name=^/" + name + "$",
                   "--format", "{{.Names}}"], timeout=8)
    if result:
        raise ValueError("disposable container cleanup unverified")


def rehearsal(role, *, call=runner, pauses=time.sleep, identifiers=None):
    if role not in RESEARCH:
        raise ValueError("unapproved research-only image identity")
    image = RESEARCH[role]
    if identifiers is None:
        identifiers = (secrets.token_hex(6), secrets.token_hex(6))
    if (not isinstance(identifiers, (list, tuple)) or len(identifiers) != 2 or
            identifiers[0] == identifiers[1] or any(
                not isinstance(x, str) or not re.fullmatch(r"[a-f0-9]{12}", x)
                for x in identifiers)):
        raise ValueError("invalid distinct disposable fixture nonces")
    name1, name2 = ("kp-legacy-isolated-" + x for x in identifiers)
    if call(["docker", "image", "inspect", "--format", "{{.Id}}", image]) != image:
        raise ValueError("pinned research image unavailable")
    created_names = []
    injected = False
    replayed = False
    cleanup = False
    try:
        # Names are prepared before launch to cover partial Docker successes.
        created_names.append(name1)
        first_id = _result_for(name1, image, call=call, pauses=pauses)
        # _result_for already verified policy + matching full ID and name.
        # Repeat binding immediately before SIGKILL to limit stale alias risk.
        binding = call(["docker", "inspect", "--format",
                        "{{.Id}}|{{.Image}}|{{.Name}}|{{.State.Running}}",
                        first_id], timeout=8)
        if binding != "|".join([first_id, image, "/" + name1, "true"]):
            raise ValueError("pre-injection container identity changed")
        killed_id = call(["docker", "kill", "--signal", "SIGKILL", first_id],
                         timeout=12)
        if killed_id != first_id:
            raise ValueError("injection did not return the pinned container")
        _stopped(name1, call=call, pauses=pauses)
        injected = True
        created_names.append(name2)
        second_id = _result_for(name2, image, call=call, pauses=pauses)
        if second_id == first_id:
            raise ValueError("same container ID reused on recovery")
        replayed = True
    finally:
        outcomes = []
        for name in reversed(created_names):
            try:
                _cleanup(name, call=call)
                outcomes.append(True)
            except (OSError, ValueError, subprocess.SubprocessError):
                outcomes.append(False)
        cleanup = len(outcomes) == len(created_names) and all(outcomes)
        if not cleanup:
            raise ValueError("one or more disposable containers remain unqualified")
    if not (injected and replayed and cleanup):
        raise ValueError("research-only failure/recovery sequence incomplete")
    return {
        "status": "RESEARCH_RESTART_AFTER_SIGKILL_PASS_NOT_LEGACY",
        "research_role": role,
        "same_pinned_research_image_before_and_after": True,
        "candidate_health_and_auth_contract_before_and_after": True,
        "isolated_sigkill_observed": True,
        "fresh_container_id_observed": True,
        "all_disposable_cleanup_verified": True,
        "network_none_readonly_and_no_persistent_mounts": True,
        "original_historical_web_or_api_images_recovered": False,
        "prior_production_image_rollback_verified": False,
        "database_or_object_store_restored": False,
        "original_release_auth_parity_verified": False,
        "production_modified": False,
        "safe_to_cutover": False,
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--research-role", choices=tuple(RESEARCH), required=True)
    options = parser.parse_args()
    try:
        outcome = rehearsal(options.research_role)
    except (OSError, ValueError, UnicodeError, subprocess.SubprocessError):
        print(json.dumps({"status": "HOLD",
                          "historical_rollback_verified": False,
                          "safe_to_cutover": False}, sort_keys=True))
        return 2
    print(json.dumps(outcome, sort_keys=True))
    return 0


if __name__ == "__main__":
    sys.exit(main())
