"""D1 ticket 03: consent-aware, replay-safe PWA finalization."""

from __future__ import annotations

import concurrent.futures
import datetime as dt
import json
import logging
import sqlite3
import threading

import pytest
from fastapi.testclient import TestClient

from dr_alex import (
    alexd,
    config,
    crypto,
    engine,
    fanout,
    llm,
    memstore,
    pairing,
    statedb,
    statefile,
)
from dr_alex.digest import SessionDigest
from safety.triage import Tier

_META = {
    "policy_version": "3.0.0",
    "copy_version": "test-copy-v1",
    "retention_policy_version": "test-retention-v1",
    "purpose_version": "test-purpose-v1",
    "locale": "en",
}


@pytest.fixture
def client():
    alexd._sessions.clear()
    if hasattr(alexd.app.state, "synthetic_finalization_seams"):
        del alexd.app.state.synthetic_finalization_seams
    with TestClient(alexd.app) as test_client:
        yield test_client
    if hasattr(alexd.app.state, "synthetic_finalization_seams"):
        del alexd.app.state.synthetic_finalization_seams


def _token(client: TestClient) -> str:
    response = client.post("/pair", json={"code": pairing.create_pairing_code()})
    assert response.status_code == 200
    return response.json()["device_token"]


def _post(client: TestClient, path: str, token: str, payload: dict):
    return client.post(path, json=payload, headers={alexd.DEVICE_HEADER: token})


def _enable_writer(monkeypatch, marker: str) -> None:
    monkeypatch.setenv("DR_ALEX_CONSENT_ENFORCEMENT", "1")
    monkeypatch.setenv("DR_ALEX_ALLOW_TEST_CONSENT", "1")
    monkeypatch.setenv("DR_ALEX_PWA_DURABLE_FINALIZATION", "1")
    monkeypatch.setattr(
        fanout._digest,
        "distill",
        lambda turns, **kwargs: SessionDigest(
            session_id=kwargs["session_id"],
            started_at=kwargs["started_at"],
            ended_at="2026-08-26T00:00:00Z",
            risk_tier_max=kwargs["risk_tier_max"],
            durable_learnings=[marker],
        ),
    )


def _start_full_grant(client: TestClient, token: str) -> str:
    response = _post(
        client,
        "/session/start",
        token,
        {
            "consent": {
                "transcript_retention": "granted",
                "durable_memory": "granted",
                **_META,
            }
        },
    )
    return response.json()["session_id"]


def test_d1_f01_no_retention_returns_same_body_free_receipt(client, monkeypatch) -> None:
    monkeypatch.setenv("DR_ALEX_CONSENT_ENFORCEMENT", "1")
    monkeypatch.setenv("DR_ALEX_ALLOW_TEST_CONSENT", "1")
    token = _token(client)
    start = _post(
        client,
        "/session/start",
        token,
        {"consent": {"transcript_retention": "denied", **_META}},
    )
    session_id = start.json()["session_id"]

    first = _post(client, "/session/end", token, {"session_id": session_id})
    second = _post(client, "/session/end", token, {"session_id": session_id})

    assert first.status_code == second.status_code == 200
    assert first.json() == second.json()
    receipt = first.json()
    assert receipt["ok"] is receipt["complete"] is True
    assert receipt["finalization"] == {
        "status": "closed_transient",
        "operation_id": receipt["finalization"]["operation_id"],
        "memory_written": False,
        "error_class": None,
    }
    with sqlite3.connect(statedb.state_db_path()) as conn:
        row = conn.execute(
            "SELECT status, payload_enc, lease_owner, lease_expires_at "
            "FROM finalization_operations WHERE session_id=?",
            (session_id,),
        ).fetchone()
    assert row == ("closed_transient", None, None, None)


def test_d1_f07_completed_retry_does_not_read_consent_store(client, monkeypatch) -> None:
    monkeypatch.setenv("DR_ALEX_CONSENT_ENFORCEMENT", "1")
    monkeypatch.setenv("DR_ALEX_ALLOW_TEST_CONSENT", "1")
    token = _token(client)
    session_id = _post(
        client,
        "/session/start",
        token,
        {"consent": {"transcript_retention": "denied", **_META}},
    ).json()["session_id"]
    first = _post(client, "/session/end", token, {"session_id": session_id})
    assert session_id not in alexd._sessions

    def fail_consent(*args, **kwargs):
        raise sqlite3.OperationalError("synthetic consent outage")

    monkeypatch.setattr(statedb, "resolve_consent", fail_consent)
    second = _post(client, "/session/end", token, {"session_id": session_id})

    assert second.status_code == 200
    assert second.json() == first.json()


@pytest.mark.parametrize(
    ("decisions", "red_turn", "expected"),
    (
        ({"transcript_retention": "granted"}, False, "finalized_no_memory_consent"),
        (
            {"transcript_retention": "granted", "durable_memory": "granted"},
            True,
            "finalized_red_withheld",
        ),
        (
            {"transcript_retention": "granted", "durable_memory": "granted"},
            False,
            "finalization_disabled",
        ),
    ),
)
def test_d1_f02_f04_terminal_statuses_are_body_free(
    client, monkeypatch, decisions, red_turn, expected
) -> None:
    monkeypatch.setenv("DR_ALEX_CONSENT_ENFORCEMENT", "1")
    monkeypatch.setenv("DR_ALEX_ALLOW_TEST_CONSENT", "1")
    token = _token(client)
    start = _post(client, "/session/start", token, {"consent": {**decisions, **_META}})
    session_id = start.json()["session_id"]
    if red_turn:
        monkeypatch.setenv("DR_ALEX_PWA_DURABLE_FINALIZATION", "1")

        def sink_bomb(*args, **kwargs):
            pytest.fail("RED finalization reached a synthetic sink")

        alexd.app.state.synthetic_finalization_seams = dict.fromkeys(
            fanout._SYNTHETIC_SEAM_KEYS, sink_bomb
        )
        turn = _post(
            client,
            "/turn",
            token,
            {"session_id": session_id, "text": "I want to kill myself"},
        )
        assert turn.status_code == 200

    response = _post(client, "/session/end", token, {"session_id": session_id})

    assert response.status_code == 200
    assert response.json()["finalization"]["status"] == expected
    with sqlite3.connect(statedb.state_db_path()) as conn:
        row = conn.execute(
            "SELECT payload_enc,lease_owner,lease_expires_at FROM finalization_operations "
            "WHERE session_id=?",
            (session_id,),
        ).fetchone()
    assert row == (None, None, None)


def test_end_rejects_active_owner_without_live_session_or_operation(client, monkeypatch) -> None:
    monkeypatch.setenv("DR_ALEX_CONSENT_ENFORCEMENT", "1")
    monkeypatch.setenv("DR_ALEX_ALLOW_TEST_CONSENT", "1")
    token = _token(client)
    session_id = _start_full_grant(client, token)
    alexd._sessions.pop(session_id)

    response = _post(client, "/session/end", token, {"session_id": session_id})

    assert response.status_code == 404
    assert response.json()["detail"] == "session_not_found"
    assert statedb.get_finalization_operation(session_id) is None
    owner = statedb.get_session_owner(session_id)
    assert owner is not None and owner.ended_at is None


def test_rc4_r08_enforcement_off_preserves_response_and_creates_no_operation(
    client, monkeypatch
) -> None:
    monkeypatch.delenv("DR_ALEX_CONSENT_ENFORCEMENT", raising=False)
    token = _token(client)
    session_id = _post(client, "/session/start", token, {}).json()["session_id"]

    response = _post(client, "/session/end", token, {"session_id": session_id})

    assert response.status_code == 200
    assert response.json() == {"ok": True}
    with sqlite3.connect(statedb.state_db_path()) as conn:
        assert conn.execute("SELECT COUNT(*) FROM finalization_operations").fetchone()[0] == 0


def test_d1_f03_session_risk_max_does_not_decrease(monkeypatch) -> None:
    outcomes = iter(
        (
            engine.TurnOutcome(tier=Tier.RED, text="synthetic red card"),
            engine.TurnOutcome(tier=Tier.GREEN, text="synthetic reply"),
        )
    )
    monkeypatch.setattr(engine, "run_turn", lambda *args, **kwargs: next(outcomes))
    session = alexd.RoomSession("risk-max-session", test_traffic=True)

    alexd._run_turn_blocking(session, "synthetic turn one")
    alexd._run_turn_blocking(session, "synthetic turn two")

    assert session.risk_tier_max is Tier.RED


def test_enabled_writer_without_synthetic_runner_is_503_and_encrypted(client, monkeypatch) -> None:
    marker = "SYNTHETIC FINALIZATION BODY"
    _enable_writer(monkeypatch, marker)
    token = _token(client)
    session_id = _start_full_grant(client, token)
    alexd._sessions[session_id].history.append(llm.Message("user", marker))

    response = _post(client, "/session/end", token, {"session_id": session_id})

    assert response.status_code == 503
    assert response.json()["finalization"]["status"] == "finalization_unavailable"
    operation = statedb.get_finalization_operation(session_id)
    assert operation is not None and operation.payload_enc is not None
    assert marker in (crypto.decrypt(operation.payload_enc) or "")
    assert marker.encode() not in statedb.state_db_path().read_bytes()


def test_partial_synthetic_runner_is_unavailable_without_distillation(client, monkeypatch) -> None:
    monkeypatch.setenv("DR_ALEX_CONSENT_ENFORCEMENT", "1")
    monkeypatch.setenv("DR_ALEX_ALLOW_TEST_CONSENT", "1")
    monkeypatch.setenv("DR_ALEX_PWA_DURABLE_FINALIZATION", "1")
    distill_calls = 0

    def distill(*args, **kwargs):
        nonlocal distill_calls
        distill_calls += 1
        return SessionDigest(
            session_id=kwargs["session_id"],
            started_at=kwargs["started_at"],
            ended_at="2026-08-26T00:00:00Z",
            risk_tier_max=kwargs["risk_tier_max"],
        )

    complete_calls = 0

    def complete(marker, **kwargs):
        nonlocal complete_calls
        complete_calls += 1
        return fanout.FanoutResult(
            session_id=marker.session_id,
            remembered=[],
            inbox_path=None,
            continuity_written=True,
            risk_tier_max="GREEN",
            durable_withheld=False,
        )

    monkeypatch.setattr(fanout._digest, "distill", distill)
    monkeypatch.setattr(fanout, "complete_digest", complete)
    alexd.app.state.synthetic_finalization_seams = {}
    token = _token(client)
    session_id = _start_full_grant(client, token)

    response = _post(client, "/session/end", token, {"session_id": session_id})

    assert response.status_code == 503
    assert response.json()["finalization"]["status"] == "finalization_unavailable"
    assert distill_calls == complete_calls == 0
    operation = statedb.get_finalization_operation(session_id)
    assert operation is not None and operation.payload_enc is not None


def test_d1_f05_synthetic_writer_finalizes_once_without_legacy_marker(
    client, monkeypatch, tmp_path
) -> None:
    marker = "SYNTHETIC FINALIZATION BODY"
    _enable_writer(monkeypatch, marker)
    remembered: list[str] = []
    idempotency_keys: list[str] = []
    continuity: list[str] = []
    inbox = tmp_path / "inbox"

    def remember(body, *, idempotency_key, **kwargs):
        remembered.append(body)
        idempotency_keys.append(idempotency_key)
        return memstore.WriteResult(ok=True, id="mem-deterministic")

    alexd.app.state.synthetic_finalization_seams = {
        "distill_fn": fanout._digest.distill,
        "remember_fn": remember,
        "scrub_fn": lambda document: document.encode(),
        "inbox_dir_fn": lambda: str(inbox),
        "load_continuity_fn": lambda: "",
        "continuity_fn": lambda digest, prior, *, now: "synthetic brief",
        "save_continuity_fn": continuity.append,
        "mirror_fn": lambda digest: (None, None),
    }
    monkeypatch.setattr(
        statefile,
        "set_unfinalized",
        lambda *args, **kwargs: pytest.fail("legacy marker touched"),
    )
    token = _token(client)
    session_id = _start_full_grant(client, token)

    first = _post(client, "/session/end", token, {"session_id": session_id})
    second = _post(client, "/session/end", token, {"session_id": session_id})

    assert first.status_code == second.status_code == 200
    assert first.json() == second.json()
    receipt = first.json()["finalization"]
    assert receipt == {
        "status": "finalized",
        "operation_id": receipt["operation_id"],
        "memory_written": True,
        "error_class": None,
    }
    assert remembered == [marker]
    assert len(idempotency_keys) == 1
    assert idempotency_keys[0].startswith("dr-alex-finalize-v1:")
    assert marker not in idempotency_keys[0]
    assert continuity == ["synthetic brief"]
    assert len(list(inbox.glob("*.md"))) == 1
    operation = statedb.get_finalization_operation(session_id)
    assert operation is not None and operation.status == "finalized"
    assert operation.payload_enc is None
    assert json.loads(operation.step_state)["memory_written"] is True


def test_deterministic_sink_ids_encode_component_boundaries() -> None:
    assert fanout._sink_id("ab", "c", "memory:0", "v1") != fanout._sink_id(
        "a", "bc", "memory:0", "v1"
    )


def test_sink_success_before_ledger_failure_reuses_one_id(tmp_path) -> None:
    digest = SessionDigest(
        session_id="c",
        started_at="2026-08-26T00:00:00Z",
        ended_at="2026-08-26T00:01:00Z",
        risk_tier_max="GREEN",
        durable_learnings=["Synthetic durable fact."],
    )

    def new_marker():
        return statefile.UnfinalizedMarker(
            session_id="c",
            started_at=digest.started_at,
            end_ts=digest.ended_at,
            inbox_filename="deterministic.md",
            digest=fanout._digest.to_jsonable(digest),
        )

    calls: list[str] = []
    effects: dict[str, str] = {}

    def remember(body, *, idempotency_key, **kwargs):
        calls.append(idempotency_key)
        assert effects.setdefault(idempotency_key, body) == body
        return memstore.WriteResult(ok=True, id="one-memory")

    def crash_after_sink(_marker):
        raise sqlite3.OperationalError("synthetic ledger failure")

    seams = {
        "remember_fn": remember,
        "scrub_fn": lambda document: document.encode(),
        "inbox_dir_fn": lambda: str(tmp_path / "inbox"),
        "load_continuity_fn": lambda: "",
        "continuity_fn": lambda digest, prior, *, now: "brief",
        "save_continuity_fn": lambda text: None,
        "mirror_fn": lambda digest: (None, None),
        "idempotency_key_fn": lambda step: fanout._sink_id("ab", "c", step, "v1"),
    }

    with pytest.raises(sqlite3.OperationalError, match="synthetic ledger failure"):
        fanout.complete_digest(new_marker(), persist_step=crash_after_sink, **seams)
    fanout.complete_digest(new_marker(), persist_step=lambda marker: None, **seams)

    assert calls == [calls[0], calls[0]]
    assert effects == {calls[0]: "Synthetic durable fact."}


def test_d1_f13_initial_operation_has_generation_one_lease(tmp_path) -> None:
    now = dt.datetime(2026, 8, 26, 12, 0, tzinfo=dt.UTC)

    operation = statedb.create_finalization(
        "lease-session",
        subject_id="subject-a",
        source="alexd",
        status="running",
        payload="synthetic replay input",
        lease_owner="worker-a",
        lease_seconds=5,
        now=now,
        path=tmp_path / "state.db",
    )

    assert operation.status == "running"
    assert operation.lease_owner == "worker-a"
    assert operation.lease_generation == 1
    assert operation.lease_expires_at == "2026-08-26T12:00:05.000000Z"


def test_create_finalization_loads_row_inside_insert_transaction(monkeypatch, tmp_path) -> None:
    monkeypatch.setattr(
        statedb,
        "get_finalization_operation",
        lambda *args, **kwargs: pytest.fail("opened a second connection after insert"),
    )

    operation = statedb.create_finalization(
        "atomic-create-session",
        subject_id="subject-a",
        source="pwa",
        status="recovery_pending",
        payload="synthetic encrypted payload",
        path=tmp_path / "state.db",
    )

    assert operation.session_id == "atomic-create-session"
    assert operation.subject_id == "subject-a"


def test_d1_f13_claim_targets_only_requested_operation(tmp_path) -> None:
    path = tmp_path / "state.db"
    now = dt.datetime(2026, 8, 26, 12, 0, tzinfo=dt.UTC)
    first = statedb.create_finalization(
        "session-a",
        subject_id="subject-a",
        source="alexd",
        status="recovery_pending",
        payload="first synthetic payload",
        now=now,
        path=path,
    )
    second = statedb.create_finalization(
        "session-b",
        subject_id="subject-b",
        source="alexd",
        status="recovery_pending",
        payload="second synthetic payload",
        now=now,
        path=path,
    )

    claimed = statedb.claim_finalization(
        first.operation_id,
        lease_owner="worker-a",
        lease_seconds=5,
        now=now,
        path=path,
    )

    current = statedb.get_finalization_operation("session-a", path=path)
    assert claimed is True
    assert current is not None
    assert current.status == "running"
    assert current.lease_owner == "worker-a"
    assert current.lease_generation == 2
    assert current.lease_expires_at == "2026-08-26T12:00:05.000000Z"
    assert statedb.get_finalization_operation("session-b", path=path) == second


def test_d1_f15_stale_generation_cannot_finalize_after_takeover(tmp_path) -> None:
    path = tmp_path / "state.db"
    started = dt.datetime(2026, 8, 26, 12, 0, tzinfo=dt.UTC)
    operation = statedb.create_finalization(
        "takeover-session",
        subject_id="subject-a",
        source="alexd",
        status="running",
        payload="synthetic replay input",
        lease_owner="worker-a",
        lease_seconds=5,
        now=started,
        path=path,
    )
    assert statedb.claim_finalization(
        operation.operation_id,
        lease_owner="worker-b",
        lease_seconds=5,
        now=started + dt.timedelta(seconds=6),
        path=path,
    )
    before = statedb.get_finalization_operation("takeover-session", path=path)
    assert before is not None
    assert before.status == "running"
    assert before.lease_owner == "worker-b"
    assert before.lease_generation == 2

    updated = statedb.update_finalization_fenced(
        operation.operation_id,
        lease_owner="worker-a",
        lease_generation=1,
        step_state=json.dumps({"memory_written": True}),
        status="finalized",
        clear_payload=True,
        release_lease=True,
        now=started + dt.timedelta(seconds=7),
        path=path,
    )

    assert updated is False
    assert statedb.get_finalization_operation("takeover-session", path=path) == before


def test_d1_f15_expired_current_generation_cannot_persist(tmp_path) -> None:
    path = tmp_path / "state.db"
    started = dt.datetime(2026, 8, 26, 12, 0, tzinfo=dt.UTC)
    operation = statedb.create_finalization(
        "expired-session",
        subject_id="subject-a",
        source="alexd",
        status="running",
        payload="synthetic replay input",
        lease_owner="worker-a",
        lease_seconds=5,
        now=started,
        path=path,
    )
    before = statedb.get_finalization_operation("expired-session", path=path)

    updated = statedb.update_finalization_fenced(
        operation.operation_id,
        lease_owner="worker-a",
        lease_generation=1,
        step_state=json.dumps({"memory_written": True}),
        status="finalized",
        clear_payload=True,
        release_lease=True,
        now=started + dt.timedelta(seconds=6),
        path=path,
    )

    assert updated is False
    assert statedb.get_finalization_operation("expired-session", path=path) == before


def test_d1_f15_current_owner_renews_without_changing_generation(tmp_path) -> None:
    path = tmp_path / "state.db"
    started = dt.datetime(2026, 8, 26, 12, 0, tzinfo=dt.UTC)
    operation = statedb.create_finalization(
        "renew-session",
        subject_id="subject-a",
        source="alexd",
        status="running",
        payload="synthetic replay input",
        lease_owner="worker-a",
        lease_seconds=5,
        now=started,
        path=path,
    )

    renewed = statedb.renew_finalization(
        operation.operation_id,
        lease_owner="worker-a",
        lease_generation=1,
        lease_seconds=5,
        now=started + dt.timedelta(seconds=4),
        path=path,
    )

    current = statedb.get_finalization_operation("renew-session", path=path)
    assert renewed is True
    assert current is not None
    assert current.lease_owner == "worker-a"
    assert current.lease_generation == 1
    assert current.lease_expires_at == "2026-08-26T12:00:09.000000Z"


@pytest.mark.parametrize(
    ("raw", "expected"),
    [(None, 5), ("invalid", 5), ("0", 1), ("31", 30), ("9", 9)],
)
def test_recovery_timeout_is_bounded_and_invalid_values_fail_closed(
    monkeypatch, raw, expected
) -> None:
    if raw is None:
        monkeypatch.delenv("DR_ALEX_RECOVERY_TIMEOUT_SECONDS", raising=False)
    else:
        monkeypatch.setenv("DR_ALEX_RECOVERY_TIMEOUT_SECONDS", raw)

    assert config.recovery_timeout_seconds() == expected


def test_d1_f13_concurrent_end_has_one_sink_owner(client, monkeypatch, tmp_path) -> None:
    marker = "SYNTHETIC CONCURRENT FINALIZATION"
    _enable_writer(monkeypatch, marker)
    started = threading.Event()
    release = threading.Event()
    lock = threading.Lock()
    calls = 0
    inbox = tmp_path / "inbox"

    def remember(body, *, idempotency_key, **kwargs):
        nonlocal calls
        with lock:
            calls += 1
            call_number = calls
        if call_number == 1:
            started.set()
            assert release.wait(timeout=5)
        return memstore.WriteResult(ok=True, id="one-memory")

    alexd.app.state.synthetic_finalization_seams = {
        "distill_fn": fanout._digest.distill,
        "remember_fn": remember,
        "scrub_fn": lambda document: document.encode(),
        "inbox_dir_fn": lambda: str(inbox),
        "load_continuity_fn": lambda: "",
        "continuity_fn": lambda digest, prior, *, now: "brief",
        "save_continuity_fn": lambda text: None,
        "mirror_fn": lambda digest: (None, None),
    }
    token = _token(client)
    session_id = _start_full_grant(client, token)
    second_client = TestClient(alexd.app)

    def finalize(http_client):
        return _post(http_client, "/session/end", token, {"session_id": session_id})

    with concurrent.futures.ThreadPoolExecutor(max_workers=2) as pool:
        first_future = pool.submit(finalize, client)
        assert started.wait(timeout=5)
        second = pool.submit(finalize, second_client).result(timeout=5)
        release.set()
        first = first_future.result(timeout=5)

    assert {first.status_code, second.status_code} == {200, 202}
    winner = first if first.status_code == 200 else second
    loser = second if first.status_code == 200 else first
    assert winner.json()["finalization"]["status"] == "finalized"
    assert loser.json()["finalization"]["status"] == "recovery_pending"
    assert calls == 1
    assert (
        winner.json()["finalization"]["operation_id"]
        == loser.json()["finalization"]["operation_id"]
    )
    operation = statedb.get_finalization_operation(session_id)
    assert operation is not None
    assert operation.lease_generation == 1
    with sqlite3.connect(statedb.state_db_path()) as conn:
        assert (
            conn.execute(
                "SELECT COUNT(*) FROM finalization_operations WHERE session_id=?", (session_id,)
            ).fetchone()[0]
            == 1
        )


def test_d1_f14_replay_converges_without_redistilling(client, monkeypatch, tmp_path) -> None:
    monkeypatch.setenv("DR_ALEX_CONSENT_ENFORCEMENT", "1")
    monkeypatch.setenv("DR_ALEX_ALLOW_TEST_CONSENT", "1")
    monkeypatch.setenv("DR_ALEX_PWA_DURABLE_FINALIZATION", "1")
    first_learning = "SYNTHETIC FIRST LEARNING"
    second_learning = "SYNTHETIC SECOND LEARNING"
    distill_calls = 0
    attempts: dict[str, int] = {}
    sink_calls: list[tuple[str, str]] = []
    inbox = tmp_path / "inbox"

    def distill(turns, *, session_id, started_at, risk_tier_max, now):
        nonlocal distill_calls
        distill_calls += 1
        return SessionDigest(
            session_id=session_id,
            started_at=started_at,
            ended_at="2026-08-26T12:00:00Z",
            risk_tier_max=risk_tier_max,
            durable_learnings=[first_learning, second_learning],
        )

    def remember(body, *, idempotency_key, **kwargs):
        attempts[body] = attempts.get(body, 0) + 1
        sink_calls.append((body, idempotency_key))
        if body == second_learning and attempts[body] == 1:
            return memstore.WriteResult(ok=False, error="synthetic_failure")
        return memstore.WriteResult(ok=True, id=f"memory-{body.split()[1].lower()}")

    alexd.app.state.synthetic_finalization_seams = {
        "distill_fn": distill,
        "remember_fn": remember,
        "scrub_fn": lambda document: document.encode(),
        "inbox_dir_fn": lambda: str(inbox),
        "load_continuity_fn": lambda: "",
        "continuity_fn": lambda digest, prior, *, now: "brief",
        "save_continuity_fn": lambda text: None,
        "mirror_fn": lambda digest: (None, None),
    }
    token = _token(client)
    session_id = _start_full_grant(client, token)

    first = _post(client, "/session/end", token, {"session_id": session_id})
    pending = statedb.get_finalization_operation(session_id)
    second = _post(client, "/session/end", token, {"session_id": session_id})
    finalized = statedb.get_finalization_operation(session_id)

    assert first.status_code == 202
    assert first.json()["finalization"]["status"] == "recovery_pending"
    assert pending is not None and pending.payload_enc is not None
    assert second.status_code == 200
    assert second.json()["finalization"]["status"] == "finalized"
    assert finalized is not None and finalized.payload_enc is None
    assert distill_calls == 1
    assert [body for body, _key in sink_calls] == [
        first_learning,
        second_learning,
        second_learning,
    ]
    assert sink_calls[1][1] == sink_calls[2][1]


def test_mirror_failure_stays_pending_and_replays_with_stable_key(
    client, monkeypatch, tmp_path
) -> None:
    marker = "SYNTHETIC MIRROR RETRY"
    _enable_writer(monkeypatch, marker)
    keys: list[str | None] = []
    inbox = tmp_path / "inbox"

    def mirror(digest, *, idempotency_key=None):
        keys.append(idempotency_key)
        if len(keys) == 1:
            raise OSError("synthetic mirror unavailable")
        return None, None

    alexd.app.state.synthetic_finalization_seams = {
        "distill_fn": fanout._digest.distill,
        "remember_fn": lambda body, **kwargs: memstore.WriteResult(ok=True, id="memory"),
        "scrub_fn": lambda document: document.encode(),
        "inbox_dir_fn": lambda: str(inbox),
        "load_continuity_fn": lambda: "",
        "continuity_fn": lambda digest, prior, *, now: "brief",
        "save_continuity_fn": lambda text: None,
        "mirror_fn": mirror,
    }
    token = _token(client)
    session_id = _start_full_grant(client, token)

    first = _post(client, "/session/end", token, {"session_id": session_id})
    first_operation = statedb.get_finalization_operation(session_id)
    assert first.status_code == 202
    assert first_operation is not None
    assert first_operation.status == "recovery_pending"
    assert first_operation.payload_enc is not None

    second = _post(client, "/session/end", token, {"session_id": session_id})
    second_operation = statedb.get_finalization_operation(session_id)
    assert second.status_code == 200
    assert second_operation is not None
    assert second_operation.status == "finalized"
    assert second_operation.payload_enc is None
    assert keys[0] == keys[1]
    assert keys[0] is not None


def test_d1_f15_stale_worker_stops_after_fenced_progress_loss(
    client, monkeypatch, tmp_path
) -> None:
    monkeypatch.setenv("DR_ALEX_CONSENT_ENFORCEMENT", "1")
    monkeypatch.setenv("DR_ALEX_ALLOW_TEST_CONSENT", "1")
    monkeypatch.setenv("DR_ALEX_PWA_DURABLE_FINALIZATION", "1")
    started_at = dt.datetime(2026, 8, 26, 12, 0, tzinfo=dt.UTC)
    first_sink_started = threading.Event()
    release_first_sink = threading.Event()
    lock = threading.Lock()
    memory_calls = 0
    worker_a_thread: int | None = None
    events: list[tuple[int, str]] = []
    inbox = tmp_path / "inbox"

    def distill(turns, *, session_id, started_at, risk_tier_max, now):
        return SessionDigest(
            session_id=session_id,
            started_at=started_at,
            ended_at="2026-08-26T12:00:01Z",
            risk_tier_max=risk_tier_max,
            durable_learnings=["SYNTHETIC TAKEOVER LEARNING"],
        )

    def remember(body, *, idempotency_key, **kwargs):
        nonlocal memory_calls, worker_a_thread
        thread_id = threading.get_ident()
        with lock:
            memory_calls += 1
            call_number = memory_calls
            events.append((thread_id, "memory"))
            if call_number == 1:
                worker_a_thread = thread_id
        if call_number == 1:
            first_sink_started.set()
            assert release_first_sink.wait(timeout=5)
        return memstore.WriteResult(ok=True, id="one-memory")

    def record(step):
        events.append((threading.get_ident(), step))

    seams = {
        "distill_fn": distill,
        "remember_fn": remember,
        "scrub_fn": lambda document: record("inbox") or document.encode(),
        "inbox_dir_fn": lambda: str(inbox),
        "load_continuity_fn": lambda: record("continuity") or "",
        "continuity_fn": lambda digest, prior, *, now: "brief",
        "save_continuity_fn": lambda text: None,
        "mirror_fn": lambda digest: record("mirror") or (None, None),
    }
    token = _token(client)
    session_id = _start_full_grant(client, token)
    owner = statedb.get_session_owner(session_id)
    assert owner is not None
    consent = statedb.resolve_consent(owner.subject_id, source=owner.source)

    def finalize(now):
        return fanout.finalize_authorized_session(
            session_id,
            owner.subject_id,
            owner.source,
            consent,
            turns=[],
            started_at="2026-08-26T12:00:00Z",
            synthetic_seams=seams,
            now=now,
        )

    with concurrent.futures.ThreadPoolExecutor(max_workers=2) as pool:
        first_future = pool.submit(finalize, started_at)
        assert first_sink_started.wait(timeout=5)
        second = pool.submit(finalize, started_at + dt.timedelta(seconds=6)).result(timeout=5)
        release_first_sink.set()
        first = first_future.result(timeout=5)

    assert first.status == second.status == "finalized"
    assert worker_a_thread is not None
    assert [step for thread_id, step in events if thread_id == worker_a_thread] == ["memory"]


def test_d1_f10_withdrawal_between_steps_erases_payload(client, monkeypatch, tmp_path) -> None:
    monkeypatch.setenv("DR_ALEX_CONSENT_ENFORCEMENT", "1")
    monkeypatch.setenv("DR_ALEX_ALLOW_TEST_CONSENT", "1")
    monkeypatch.setenv("DR_ALEX_PWA_DURABLE_FINALIZATION", "1")
    events: list[str] = []
    inbox = tmp_path / "inbox"
    token = _token(client)
    session_id = _start_full_grant(client, token)
    owner = statedb.get_session_owner(session_id)
    assert owner is not None

    def distill(turns, *, session_id, started_at, risk_tier_max, now):
        return SessionDigest(
            session_id=session_id,
            started_at=started_at,
            ended_at="2026-08-26T12:00:01Z",
            risk_tier_max=risk_tier_max,
            durable_learnings=["SYNTHETIC CONSENT LEARNING"],
        )

    def remember(body, *, idempotency_key, **kwargs):
        events.append("memory")
        statedb.record_consent(
            subject_id=owner.subject_id,
            actor_principal=owner.actor_principal,
            source=owner.source,
            consent={"durable_memory": "withdrawn", **_META},
        )
        return memstore.WriteResult(ok=True, id="one-memory")

    def record(step):
        events.append(step)

    alexd.app.state.synthetic_finalization_seams = {
        "distill_fn": distill,
        "remember_fn": remember,
        "scrub_fn": lambda document: record("inbox") or document.encode(),
        "inbox_dir_fn": lambda: str(inbox),
        "load_continuity_fn": lambda: record("continuity") or "",
        "continuity_fn": lambda digest, prior, *, now: "brief",
        "save_continuity_fn": lambda text: None,
        "mirror_fn": lambda digest: record("mirror") or (None, None),
    }

    response = _post(client, "/session/end", token, {"session_id": session_id})
    operation = statedb.get_finalization_operation(session_id)

    assert response.status_code == 200
    assert response.json()["finalization"] == {
        "status": "finalized_no_memory_consent",
        "operation_id": response.json()["finalization"]["operation_id"],
        "memory_written": True,
        "error_class": "consent_withdrawn",
    }
    assert operation is not None and operation.payload_enc is None
    assert events == ["memory"]


def test_d1_f10_withdrawn_recovery_resolves_before_claim_and_never_decrypts(
    client, monkeypatch
) -> None:
    monkeypatch.setenv("DR_ALEX_CONSENT_ENFORCEMENT", "1")
    monkeypatch.setenv("DR_ALEX_ALLOW_TEST_CONSENT", "1")
    token = _token(client)
    session_id = _start_full_grant(client, token)
    owner = statedb.get_session_owner(session_id)
    assert owner is not None
    stale_consent = statedb.resolve_consent(owner.subject_id, owner.source)
    statedb.create_finalization(
        session_id,
        subject_id=owner.subject_id,
        source=owner.source,
        status="finalization_unavailable",
        payload='{"history":[["user","SYNTHETIC RECOVERY BODY"]]}',
    )
    statedb.record_consent(
        subject_id=owner.subject_id,
        actor_principal=owner.actor_principal,
        source=owner.source,
        consent={
            "transcript_retention": "withdrawn",
            "durable_memory": "withdrawn",
            **_META,
        },
    )
    events: list[str] = []
    resolve_consent = statedb.resolve_consent
    claim_finalization = statedb.claim_finalization

    def resolve(*args, **kwargs):
        events.append("consent")
        return resolve_consent(*args, **kwargs)

    def claim(*args, **kwargs):
        events.append("claim")
        return claim_finalization(*args, **kwargs)

    monkeypatch.setattr(statedb, "resolve_consent", resolve)
    monkeypatch.setattr(statedb, "claim_finalization", claim)
    monkeypatch.setattr(
        crypto,
        "decrypt",
        lambda *_args, **_kwargs: pytest.fail("payload decrypted after withdrawal"),
    )

    receipt = fanout.finalize_authorized_session(
        session_id,
        owner.subject_id,
        owner.source,
        stale_consent,
    )
    operation = statedb.get_finalization_operation(session_id)

    assert events == ["consent", "claim"]
    assert receipt.status == "finalized_no_memory_consent"
    assert receipt.error_class == "consent_withdrawn"
    assert operation is not None and operation.payload_enc is None


def test_d1_f13_claim_loser_never_decrypts_or_runs_sink(client, monkeypatch) -> None:
    monkeypatch.setenv("DR_ALEX_CONSENT_ENFORCEMENT", "1")
    monkeypatch.setenv("DR_ALEX_ALLOW_TEST_CONSENT", "1")
    token = _token(client)
    session_id = _start_full_grant(client, token)
    owner = statedb.get_session_owner(session_id)
    assert owner is not None
    consent = statedb.resolve_consent(owner.subject_id, owner.source)
    now = dt.datetime(2026, 8, 26, 12, 0, tzinfo=dt.UTC)
    operation = statedb.create_finalization(
        session_id,
        subject_id=owner.subject_id,
        source=owner.source,
        status="running",
        payload='{"history":[["user","SYNTHETIC OWNED BODY"]]}',
        lease_owner="current-worker",
        lease_seconds=30,
        now=now,
    )
    monkeypatch.setattr(
        crypto,
        "decrypt",
        lambda *_args, **_kwargs: pytest.fail("claim loser decrypted payload"),
    )
    monkeypatch.setattr(
        fanout,
        "complete_digest",
        lambda *_args, **_kwargs: pytest.fail("claim loser reached sink writer"),
    )

    receipt = fanout.finalize_authorized_session(
        session_id,
        owner.subject_id,
        owner.source,
        consent,
        now=now + dt.timedelta(seconds=1),
    )

    assert receipt.status == "recovery_pending"
    assert receipt.operation_id == operation.operation_id
    assert statedb.get_finalization_operation(session_id) == operation


def test_d1_f11_policy_change_does_not_reextract_completed_session(
    client, monkeypatch, tmp_path
) -> None:
    monkeypatch.setenv("DR_ALEX_CONSENT_ENFORCEMENT", "1")
    monkeypatch.setenv("DR_ALEX_ALLOW_TEST_CONSENT", "1")
    monkeypatch.setenv("DR_ALEX_PWA_DURABLE_FINALIZATION", "1")
    monkeypatch.setenv("DR_ALEX_MEMORY_POLICY_VERSION", "4.2.0")
    marker = "SYNTHETIC POLICY VERSION LEARNING"
    distill_calls = 0
    idempotency_keys: list[str] = []

    def distill(turns, *, session_id, started_at, risk_tier_max, now):
        nonlocal distill_calls
        distill_calls += 1
        return SessionDigest(
            session_id=session_id,
            started_at=started_at,
            ended_at="2026-08-26T12:00:00Z",
            risk_tier_max=risk_tier_max,
            durable_learnings=[marker],
        )

    def remember(body, *, idempotency_key, **kwargs):
        idempotency_keys.append(idempotency_key)
        return memstore.WriteResult(ok=True, id="one-memory")

    alexd.app.state.synthetic_finalization_seams = {
        "distill_fn": distill,
        "remember_fn": remember,
        "scrub_fn": lambda document: document.encode(),
        "inbox_dir_fn": lambda: str(tmp_path / "inbox"),
        "load_continuity_fn": lambda: "",
        "continuity_fn": lambda digest, prior, *, now: "brief",
        "save_continuity_fn": lambda text: None,
        "mirror_fn": lambda digest: (None, None),
    }
    token = _token(client)
    consent_meta = {**_META, "policy_version": "9.9.9"}
    session_id = _post(
        client,
        "/session/start",
        token,
        {
            "consent": {
                "transcript_retention": "granted",
                "durable_memory": "granted",
                **consent_meta,
            }
        },
    ).json()["session_id"]
    owner = statedb.get_session_owner(session_id)
    assert owner is not None

    first = _post(client, "/session/end", token, {"session_id": session_id})
    monkeypatch.setenv("DR_ALEX_MEMORY_POLICY_VERSION", "5.0.0")
    alexd.app.state.synthetic_finalization_seams["distill_fn"] = lambda *args, **kwargs: (
        pytest.fail("completed session redistilled after policy change")
    )
    monkeypatch.setattr(
        crypto,
        "decrypt",
        lambda *_args, **_kwargs: pytest.fail("completed payload decrypted after policy change"),
    )
    second = _post(client, "/session/end", token, {"session_id": session_id})

    assert first.status_code == second.status_code == 200
    assert second.json() == first.json()
    assert distill_calls == 1
    assert idempotency_keys == [fanout._sink_id(owner.subject_id, session_id, "memory:0", "4.2.0")]
    assert config.memory_policy_version() == "5.0.0"


def test_session_start_recovers_same_subject_before_memory_assembly(
    client, monkeypatch, tmp_path
) -> None:
    monkeypatch.setenv("DR_ALEX_CONSENT_ENFORCEMENT", "1")
    monkeypatch.setenv("DR_ALEX_ALLOW_TEST_CONSENT", "1")
    monkeypatch.setenv("DR_ALEX_PWA_DURABLE_FINALIZATION", "1")
    subject_id = pairing.local_subject_id()
    prior_session_id = "synthetic-prior-session"
    events: list[str] = []
    statedb.create_finalization(
        prior_session_id,
        subject_id=subject_id,
        source="pwa",
        status="finalization_unavailable",
        payload=json.dumps(
            {
                "history": [["user", "SYNTHETIC START RECOVERY BODY"]],
                "inbox_filename": "synthetic-start-recovery.md",
                "policy_version": "3.0.0",
                "risk_tier_max": "GREEN",
                "started_at": "2026-08-26T12:00:00Z",
            }
        ),
    )

    def distill(turns, *, session_id, started_at, risk_tier_max, now):
        events.append("distill")
        return SessionDigest(
            session_id=session_id,
            started_at=started_at,
            ended_at="2026-08-26T12:01:00Z",
            risk_tier_max=risk_tier_max,
            durable_learnings=["SYNTHETIC RECOVERED LEARNING"],
        )

    def remember(body, *, idempotency_key, **kwargs):
        events.append("memory")
        return memstore.WriteResult(ok=True, id="recovered-memory")

    alexd.app.state.synthetic_finalization_seams = {
        "distill_fn": distill,
        "remember_fn": remember,
        "scrub_fn": lambda document: document.encode(),
        "inbox_dir_fn": lambda: str(tmp_path / "inbox"),
        "load_continuity_fn": lambda: "",
        "continuity_fn": lambda digest, prior, *, now: "brief",
        "save_continuity_fn": lambda text: None,
        "mirror_fn": lambda digest: (None, None),
    }
    monkeypatch.setattr(
        alexd.RoomSession,
        "assemble_memory",
        lambda self: events.append("assemble"),
    )
    token = _token(client)

    response = _post(
        client,
        "/session/start",
        token,
        {
            "consent": {
                "transcript_retention": "granted",
                "durable_memory": "granted",
                **_META,
            }
        },
    )

    assert response.status_code == 200
    assert events == ["distill", "memory", "assemble"]
    operation = statedb.get_finalization_operation(prior_session_id)
    assert operation is not None and operation.status == "finalized"


def test_session_start_timeout_skips_memory_assembly_while_recovery_runs(
    client, monkeypatch, tmp_path
) -> None:
    monkeypatch.setenv("DR_ALEX_CONSENT_ENFORCEMENT", "1")
    monkeypatch.setenv("DR_ALEX_ALLOW_TEST_CONSENT", "1")
    monkeypatch.setenv("DR_ALEX_PWA_DURABLE_FINALIZATION", "1")
    monkeypatch.setattr(config, "recovery_timeout_seconds", lambda: 0.5)
    subject_id = pairing.local_subject_id()
    prior_session_id = "synthetic-timeout-recovery"
    sink_started = threading.Event()
    release_sink = threading.Event()
    sink_finished = threading.Event()
    assembly_events: list[str] = []
    statedb.create_finalization(
        prior_session_id,
        subject_id=subject_id,
        source="pwa",
        status="recovery_pending",
        payload=json.dumps(
            {
                "history": [["user", "SYNTHETIC TIMEOUT RECOVERY BODY"]],
                "inbox_filename": "synthetic-timeout-recovery.md",
                "policy_version": "3.0.0",
                "risk_tier_max": "GREEN",
                "started_at": "2026-08-26T12:00:00Z",
            }
        ),
    )

    def remember(body, *, idempotency_key, **kwargs):
        sink_started.set()
        assert release_sink.wait(timeout=5)
        sink_finished.set()
        return memstore.WriteResult(ok=True, id="recovered-memory")

    def distill(turns, *, session_id, started_at, risk_tier_max, now):
        return SessionDigest(
            session_id=session_id,
            started_at=started_at,
            ended_at="2026-08-26T12:01:00Z",
            risk_tier_max=risk_tier_max,
            durable_learnings=["SYNTHETIC TIMEOUT LEARNING"],
        )

    alexd.app.state.synthetic_finalization_seams = {
        "distill_fn": distill,
        "remember_fn": remember,
        "scrub_fn": lambda document: document.encode(),
        "inbox_dir_fn": lambda: str(tmp_path / "inbox"),
        "load_continuity_fn": lambda: "",
        "continuity_fn": lambda digest, prior, *, now: "brief",
        "save_continuity_fn": lambda text: None,
        "mirror_fn": lambda digest: (None, None),
    }

    def assemble(session):
        assembly_events.append(
            "overlap" if sink_started.is_set() and not sink_finished.is_set() else "safe"
        )

    monkeypatch.setattr(alexd.RoomSession, "assemble_memory", assemble)
    token = _token(client)
    response = _post(
        client,
        "/session/start",
        token,
        {
            "consent": {
                "transcript_retention": "granted",
                "durable_memory": "granted",
                **_META,
            }
        },
    )
    assert sink_started.is_set()
    release_sink.set()
    assert sink_finished.wait(timeout=5)

    assert response.status_code == 200
    assert assembly_events == []


def test_unexpected_finalization_error_releases_lease_and_reraises(
    client, monkeypatch, caplog, tmp_path
) -> None:
    marker = "SYNTHETIC ERROR MESSAGE MUST NOT BE LOGGED"
    _enable_writer(monkeypatch, marker)

    class SyntheticProgrammingError(RuntimeError):
        pass

    def fail_distill(*args, **kwargs):
        raise SyntheticProgrammingError(marker)

    alexd.app.state.synthetic_finalization_seams = {
        "distill_fn": fail_distill,
        "remember_fn": lambda *args, **kwargs: pytest.fail("sink called after distill error"),
        "scrub_fn": lambda document: document.encode(),
        "inbox_dir_fn": lambda: str(tmp_path / "inbox"),
        "load_continuity_fn": lambda: "",
        "continuity_fn": lambda digest, prior, *, now: "brief",
        "save_continuity_fn": lambda text: None,
        "mirror_fn": lambda digest: (None, None),
    }
    token = _token(client)
    session_id = _start_full_grant(client, token)

    with (
        caplog.at_level(logging.WARNING, logger="dr_alex.fanout"),
        pytest.raises(SyntheticProgrammingError, match=marker),
    ):
        _post(client, "/session/end", token, {"session_id": session_id})

    operation = statedb.get_finalization_operation(session_id)
    assert operation is not None
    assert operation.status == "recovery_pending"
    assert operation.payload_enc is not None
    assert operation.lease_owner is operation.lease_expires_at is None
    assert operation.error_class == "SyntheticProgrammingError"
    assert "SyntheticProgrammingError" in caplog.text
    assert marker not in caplog.text


def test_programming_error_from_memory_sink_is_fenced_and_reraised(
    client, monkeypatch, tmp_path
) -> None:
    marker = "SYNTHETIC MEMORY PROGRAMMING ERROR"
    _enable_writer(monkeypatch, marker)

    def fail_remember(body, **kwargs):
        raise TypeError(marker)

    alexd.app.state.synthetic_finalization_seams = {
        "distill_fn": fanout._digest.distill,
        "remember_fn": fail_remember,
        "scrub_fn": lambda document: document.encode(),
        "inbox_dir_fn": lambda: str(tmp_path / "inbox"),
        "load_continuity_fn": lambda: "",
        "continuity_fn": lambda digest, prior, *, now: "brief",
        "save_continuity_fn": lambda text: None,
        "mirror_fn": lambda digest: (None, None),
    }
    token = _token(client)
    session_id = _start_full_grant(client, token)

    with pytest.raises(TypeError, match=marker):
        _post(client, "/session/end", token, {"session_id": session_id})

    operation = statedb.get_finalization_operation(session_id)
    assert operation is not None
    assert operation.status == "recovery_pending"
    assert operation.payload_enc is not None
    assert operation.lease_owner is operation.lease_expires_at is None
    assert operation.error_class == "TypeError"


def test_d1_f09_persisted_files_and_logs_contain_no_plaintext_canary(
    client, monkeypatch, caplog, tmp_path
) -> None:
    body_marker = "SYNTHETIC_PLAINTEXT_BODY_CANARY_6E4D"
    digest_marker = "SYNTHETIC_PLAINTEXT_DIGEST_CANARY_9A71"
    _enable_writer(monkeypatch, body_marker)

    def distill(turns, *, session_id, started_at, risk_tier_max, now):
        return SessionDigest(
            session_id=session_id,
            started_at=started_at,
            ended_at="2026-08-26T12:00:00Z",
            risk_tier_max=risk_tier_max,
            durable_learnings=[digest_marker],
        )

    def scrub_fails(document):
        raise memstore.ScrubError("synthetic scrub failure")

    alexd.app.state.synthetic_finalization_seams = {
        "distill_fn": distill,
        "remember_fn": lambda *args, **kwargs: memstore.WriteResult(
            ok=False, error="synthetic store failure"
        ),
        "scrub_fn": scrub_fails,
        "inbox_dir_fn": lambda: str(tmp_path / "inbox"),
        "load_continuity_fn": lambda: "",
        "continuity_fn": lambda digest, prior, *, now: "synthetic brief",
        "save_continuity_fn": lambda text: None,
        "mirror_fn": lambda digest: (None, None),
    }
    token = _token(client)
    session_id = _start_full_grant(client, token)
    alexd._sessions[session_id].history.append(llm.Message("user", body_marker))
    state_path = tmp_path / "session_state.json"
    state_path.write_text('{"version":1,"unfinalized":null}', encoding="utf-8")
    wal_connection = sqlite3.connect(statedb.state_db_path())
    assert wal_connection.execute("PRAGMA journal_mode=WAL").fetchone()[0] == "wal"
    wal_connection.execute("PRAGMA wal_autocheckpoint=0")
    wal_connection.commit()
    wal_connection.execute("BEGIN")
    wal_connection.execute("SELECT COUNT(*) FROM finalization_operations").fetchone()
    try:
        with caplog.at_level(logging.WARNING):
            response = _post(client, "/session/end", token, {"session_id": session_id})
        operation = statedb.get_finalization_operation(session_id)
        assert response.status_code == 202
        assert operation is not None and operation.payload_enc is not None
        decrypted = crypto.decrypt(operation.payload_enc) or ""
        assert digest_marker in decrypted
        assert body_marker not in decrypted
        persisted = {path: path.read_bytes() for path in tmp_path.rglob("*") if path.is_file()}
        assert statedb.state_db_path().with_name("state.db-wal") in persisted
        for content in persisted.values():
            assert body_marker.encode() not in content
            assert digest_marker.encode() not in content
        assert body_marker not in caplog.text
        assert digest_marker not in caplog.text
    finally:
        wal_connection.close()


def test_section16_finalization_observability_is_body_free(client, monkeypatch, caplog) -> None:
    marker = "SYNTHETIC OBSERVABILITY BODY MUST NOT BE LOGGED"
    _enable_writer(monkeypatch, marker)
    caplog.set_level(logging.INFO, logger="dr_alex.alexd")
    caplog.set_level(logging.INFO, logger="dr_alex.statedb")
    token = _token(client)
    session_id = _start_full_grant(client, token)
    owner = statedb.get_session_owner(session_id)
    assert owner is not None
    alexd._sessions[session_id].history.append(llm.Message("user", marker))

    first = _post(client, "/session/end", token, {"session_id": session_id})
    second = _post(client, "/session/end", token, {"session_id": session_id})

    assert first.status_code == second.status_code == 503
    assert "event=consent_decision source=pwa scope=transcript_retention" in caplog.text
    assert "event=consent_decision source=pwa scope=durable_memory" in caplog.text
    assert "event=finalization source=pwa status=finalization_unavailable" in caplog.text
    assert "pending_count=1" in caplog.text
    assert "oldest_pending_seconds=" in caplog.text
    assert "duplicate_end_count=0" in caplog.text
    assert "duplicate_end_count=1" in caplog.text
    assert "duration_ms=" in caplog.text
    assert "error_class=runner_unavailable" in caplog.text
    assert marker not in caplog.text
    assert session_id not in caplog.text
    assert owner.subject_id not in caplog.text
    assert owner.actor_principal not in caplog.text
    assert token not in caplog.text


def test_d1_f06_partial_synthetic_failure_keeps_encrypted_operation_pending(
    client, monkeypatch, tmp_path
) -> None:
    _enable_writer(monkeypatch, "SYNTHETIC PARTIAL FAILURE")

    def scrub_fails(document):
        raise memstore.ScrubError("synthetic scrub failure")

    alexd.app.state.synthetic_finalization_seams = {
        "distill_fn": fanout._digest.distill,
        "remember_fn": lambda *args, **kwargs: memstore.WriteResult(ok=True, id="unused"),
        "scrub_fn": scrub_fails,
        "inbox_dir_fn": lambda: str(tmp_path / "inbox"),
        "load_continuity_fn": lambda: "",
        "continuity_fn": lambda digest, prior, *, now: "brief",
        "save_continuity_fn": lambda text: None,
        "mirror_fn": lambda digest: (None, None),
    }
    token = _token(client)
    session_id = _start_full_grant(client, token)

    response = _post(client, "/session/end", token, {"session_id": session_id})
    operation = statedb.get_finalization_operation(session_id)

    assert response.status_code == 202
    assert operation is not None
    assert operation.status == "recovery_pending"
    assert operation.payload_enc is not None
    assert operation.lease_owner is operation.lease_expires_at is None
    assert operation.error_class == "fanout_incomplete"


def test_d1_f08_overlapping_sessions_keep_separate_rows_and_payloads(
    client, monkeypatch, tmp_path
) -> None:
    _enable_writer(monkeypatch, "SYNTHETIC OVERLAP")
    inbox = tmp_path / "inbox"

    def mirror_fails(digest, *, idempotency_key=None):
        raise OSError("synthetic mirror unavailable")

    alexd.app.state.synthetic_finalization_seams = {
        "distill_fn": fanout._digest.distill,
        "remember_fn": lambda *args, **kwargs: memstore.WriteResult(ok=True, id="unused"),
        "scrub_fn": lambda document: document.encode(),
        "inbox_dir_fn": lambda: str(inbox),
        "load_continuity_fn": lambda: "",
        "continuity_fn": lambda digest, prior, *, now: "brief",
        "save_continuity_fn": lambda text: None,
        "mirror_fn": mirror_fails,
    }
    token = _token(client)
    first_session = _start_full_grant(client, token)
    second_session = _start_full_grant(client, token)
    alexd._sessions[first_session].history.append(llm.Message("user", "SYNTHETIC FIRST"))
    alexd._sessions[second_session].history.append(llm.Message("user", "SYNTHETIC SECOND"))

    first = _post(client, "/session/end", token, {"session_id": first_session})
    second = _post(client, "/session/end", token, {"session_id": second_session})
    first_operation = statedb.get_finalization_operation(first_session)
    second_operation = statedb.get_finalization_operation(second_session)

    assert first.status_code == second.status_code == 202
    assert first_operation is not None and second_operation is not None
    assert first_operation.operation_id != second_operation.operation_id
    assert first_operation.session_id == first_session
    assert second_operation.session_id == second_session
    assert first_operation.status == second_operation.status == "recovery_pending"
    assert first_operation.payload_enc is not None
    assert second_operation.payload_enc is not None
    assert first_operation.payload_enc != second_operation.payload_enc
    assert first_session in (crypto.decrypt(first_operation.payload_enc) or "")
    assert second_session in (crypto.decrypt(second_operation.payload_enc) or "")
    assert len(list(inbox.glob("*.md"))) == 2


def test_d1_f12_pending_end_response_is_explicitly_incomplete(client, monkeypatch) -> None:
    monkeypatch.setenv("DR_ALEX_CONSENT_ENFORCEMENT", "1")
    monkeypatch.setenv("DR_ALEX_ALLOW_TEST_CONSENT", "1")
    monkeypatch.setenv("DR_ALEX_PWA_DURABLE_FINALIZATION", "1")
    token = _token(client)
    session_id = _start_full_grant(client, token)
    owner = statedb.get_session_owner(session_id)
    assert owner is not None
    statedb.create_finalization(
        session_id,
        subject_id=owner.subject_id,
        source=owner.source,
        status="running",
        payload='{"history":[],"policy_version":"3.0.0"}',
        lease_owner="synthetic-active-worker",
        lease_seconds=30,
    )

    response = _post(client, "/session/end", token, {"session_id": session_id})

    assert response.status_code == 202
    assert response.json()["ok"] is False
    assert response.json()["complete"] is False
    assert response.json()["finalization"]["status"] == "recovery_pending"


def test_rc4_r05_worker_cannot_finalize_after_lease_expires_during_mirror(
    client, monkeypatch, tmp_path
) -> None:
    monkeypatch.setenv("DR_ALEX_CONSENT_ENFORCEMENT", "1")
    monkeypatch.setenv("DR_ALEX_ALLOW_TEST_CONSENT", "1")
    monkeypatch.setenv("DR_ALEX_PWA_DURABLE_FINALIZATION", "1")
    token = _token(client)
    session_id = _start_full_grant(client, token)
    owner = statedb.get_session_owner(session_id)
    assert owner is not None
    started = dt.datetime(2026, 8, 26, 12, 0, tzinfo=dt.UTC)

    class FakeDateTime:
        current = started

        @classmethod
        def now(cls, tz=None):
            return cls.current

    class FakeDatetimeModule:
        UTC = dt.UTC
        datetime = FakeDateTime

    monkeypatch.setattr(fanout, "_dt", FakeDatetimeModule)

    def distill(turns, *, session_id, started_at, risk_tier_max, now):
        return SessionDigest(
            session_id=session_id,
            started_at=started_at,
            ended_at="2026-08-26T12:01:00Z",
            risk_tier_max=risk_tier_max,
        )

    def mirror(digest):
        FakeDateTime.current = started + dt.timedelta(seconds=6)
        return None, None

    seams = {
        "distill_fn": distill,
        "remember_fn": lambda *args, **kwargs: memstore.WriteResult(ok=True, id="unused"),
        "scrub_fn": lambda document: document.encode(),
        "inbox_dir_fn": lambda: str(tmp_path / "inbox"),
        "load_continuity_fn": lambda: "",
        "continuity_fn": lambda digest, prior, *, now: "brief",
        "save_continuity_fn": lambda text: None,
        "mirror_fn": mirror,
    }

    receipt = fanout.finalize_authorized_session(
        session_id,
        owner.subject_id,
        owner.source,
        turns=[],
        started_at="2026-08-26T12:00:00Z",
        synthetic_seams=seams,
    )
    operation = statedb.get_finalization_operation(session_id)

    assert receipt.status == "recovery_pending"
    assert operation is not None
    assert operation.status == "running"
    assert operation.payload_enc is not None


@pytest.mark.parametrize(
    ("failure", "expected_error"),
    (("crypto", "CryptoError"), ("io", "OSError")),
)
def test_operational_finalization_error_returns_recoverable_202(
    client, monkeypatch, tmp_path, failure, expected_error
) -> None:
    _enable_writer(monkeypatch, "SYNTHETIC OPERATIONAL ERROR")

    def distill(turns, *, session_id, started_at, risk_tier_max, now):
        return SessionDigest(
            session_id=session_id,
            started_at=started_at,
            ended_at="2026-08-26T12:01:00Z",
            risk_tier_max=risk_tier_max,
        )

    def scrub(document):
        if failure == "io":
            raise OSError("synthetic sink failure")
        return document.encode()

    alexd.app.state.synthetic_finalization_seams = {
        "distill_fn": distill,
        "remember_fn": lambda *args, **kwargs: memstore.WriteResult(ok=True, id="unused"),
        "scrub_fn": scrub,
        "inbox_dir_fn": lambda: str(tmp_path / "inbox"),
        "load_continuity_fn": lambda: "",
        "continuity_fn": lambda digest, prior, *, now: "brief",
        "save_continuity_fn": lambda text: None,
        "mirror_fn": lambda digest: (None, None),
    }
    if failure == "crypto":

        def fail_decrypt(token):
            raise crypto.CryptoError("synthetic corrupt payload")

        monkeypatch.setattr(crypto, "decrypt", fail_decrypt)
    token = _token(client)
    session_id = _start_full_grant(client, token)

    response = _post(client, "/session/end", token, {"session_id": session_id})
    operation = statedb.get_finalization_operation(session_id)

    assert response.status_code == 202
    assert response.json()["ok"] is response.json()["complete"] is False
    assert response.json()["finalization"]["error_class"] == expected_error
    assert operation is not None
    assert operation.status == "recovery_pending"
    assert operation.payload_enc is not None
    assert operation.lease_owner is operation.lease_expires_at is None
