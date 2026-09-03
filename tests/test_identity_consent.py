"""Tickets 01-02: stable identity, consent, and transcript policy."""

from __future__ import annotations

import datetime as dt
import logging
import sqlite3
import threading
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from dr_alex import alexd, engine, llm, pairing, statedb

_NOW = dt.datetime(2026, 8, 23, 12, tzinfo=dt.UTC)
_SUBJECT = "sub_synthetic"
_ACTOR = "device:synthetic"
_SOURCE = "pwa"
_META = {
    "policy_version": "3.0.0",
    "copy_version": "test-copy-v1",
    "retention_policy_version": "test-retention-v1",
    "purpose_version": "test-purpose-v1",
    "locale": "en",
}
_LOW_ID = "01JAAA00000000000000000000"
_HIGH_ID = "01JZZZ00000000000000000000"


def _paired_device() -> pairing.DeviceToken:
    device = pairing.redeem_pairing_code(pairing.create_pairing_code(now=_NOW), now=_NOW)
    assert device is not None
    return device


def _consent(**decisions: Any) -> dict[str, Any]:
    return {**decisions, **_META}


def _record(path: Path, now: dt.datetime = _NOW, **decisions: str) -> list[str]:
    return statedb.record_consent(
        subject_id=_SUBJECT,
        actor_principal=_ACTOR,
        source=_SOURCE,
        consent=_consent(**decisions),
        now=now,
        path=path,
    )


def _insert_receipt(
    path: Path,
    receipt_id: str,
    decision: str,
    recorded_at: str,
    *,
    scope: str = "transcript_retention",
) -> None:
    statedb.init_db(path)
    row = (
        receipt_id,
        _SUBJECT,
        _ACTOR,
        _SOURCE,
        scope,
        decision,
        recorded_at,
        None,
        *_META.values(),
        "api_test",
        None,
    )
    with statedb._policy_connect(path) as conn:
        conn.execute("INSERT INTO consent_receipts VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)", row)


def _resolve(path: Path, now: dt.datetime = _NOW) -> statedb.EffectiveConsent:
    return statedb.resolve_consent(_SUBJECT, _SOURCE, now=now, path=path)


def test_d1_i01_valid_token_returns_matched_device_principal() -> None:
    device = _paired_device()
    assert pairing.resolve_device_token(device.token, now=_NOW) == pairing.DevicePrincipal(
        device_id=device.id,
        actor_principal=f"device:{device.id}",
    )


def test_d1_i02_revoked_or_unknown_token_returns_none() -> None:
    device = _paired_device()
    assert pairing.revoke_device(device.id)
    assert pairing.resolve_device_token(device.token, now=_NOW) is None
    assert pairing.resolve_device_token("unknown", now=_NOW) is None


def test_d1_i05_local_subject_is_stable_and_opaque() -> None:
    first = pairing.local_subject_id()
    assert pairing.local_subject_id() == first
    assert first.startswith("sub_")
    assert len(first) == 26


def test_d1_c01_c02_v1_migration_preserves_rows_and_is_idempotent(tmp_path) -> None:
    path = tmp_path / "state.db"
    with sqlite3.connect(path) as conn:
        conn.execute("CREATE TABLE sessions (id TEXT PRIMARY KEY, started_ts TEXT NOT NULL)")
        conn.execute("INSERT INTO sessions VALUES ('existing', '2026-08-23T12:00:00Z')")
        conn.execute("PRAGMA user_version = 1")
    statedb.init_db(path)
    statedb.init_db(path)
    with sqlite3.connect(path) as conn:
        tables = {
            row[0] for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")
        }
        assert conn.execute("SELECT id FROM sessions").fetchall() == [("existing",)]
        assert conn.execute("PRAGMA user_version").fetchone()[0] == statedb._SCHEMA_VERSION
    assert {"consent_receipts", "session_owners", "finalization_operations"} <= tables


def test_d1_c06_absent_consent_resolves_all_durable_scopes_to_deny(tmp_path) -> None:
    consent = _resolve(tmp_path / "state.db")
    assert consent.transcript_retention is False
    assert consent.durable_memory is False
    assert consent.cross_surface_recall is False


def test_d1_c07_grant_then_withdraw_resolves_to_deny(tmp_path) -> None:
    path = tmp_path / "state.db"
    _record(path, transcript_retention="granted", durable_memory="granted")
    _record(
        path,
        _NOW + dt.timedelta(seconds=1),
        transcript_retention="withdrawn",
        durable_memory="withdrawn",
    )
    consent = _resolve(path, _NOW + dt.timedelta(seconds=2))
    assert consent.transcript_retention is False
    assert consent.durable_memory is False


def test_d1_c08_equal_timestamp_higher_ulid_wins(tmp_path) -> None:
    path = tmp_path / "state.db"
    timestamp = "2026-08-23T12:00:00Z"
    _insert_receipt(path, _LOW_ID, "denied", timestamp)
    _insert_receipt(path, _HIGH_ID, "granted", timestamp)
    consent = _resolve(path)
    assert consent.transcript_retention is True
    assert consent.transcript_receipt_id == _HIGH_ID


def test_d1_c09_malformed_stored_timestamp_denies_with_body_free_diagnostic(
    tmp_path, caplog
) -> None:
    path = tmp_path / "state.db"
    _insert_receipt(path, "01JBAD00000000000000000000", "granted", "not-a-timestamp")
    with caplog.at_level(logging.WARNING, logger="dr_alex.statedb"):
        consent = _resolve(path)
    assert consent.transcript_retention is False
    assert "invalid_timestamp" in caplog.text
    assert _SUBJECT not in caplog.text
    assert _ACTOR not in caplog.text


def test_d1_c09_malformed_later_receipt_cannot_expose_an_older_grant(tmp_path) -> None:
    path = tmp_path / "state.db"
    _record(path, transcript_retention="granted")
    _insert_receipt(path, _HIGH_ID, "granted", "")
    assert _resolve(path).transcript_retention is False


def test_d1_c07_resolution_orders_valid_timestamps_as_instants(tmp_path) -> None:
    path = tmp_path / "state.db"
    _insert_receipt(path, _LOW_ID, "granted", "2026-08-23T12:00:00Z")
    _insert_receipt(path, _HIGH_ID, "withdrawn", "2026-08-23T12:00:00.500000Z")
    consent = _resolve(path, _NOW + dt.timedelta(seconds=1))
    assert consent.transcript_retention is False
    assert consent.transcript_receipt_id == _HIGH_ID


def test_d1_scope_reserved_cross_surface_grant_has_no_behavior(tmp_path) -> None:
    path = tmp_path / "state.db"
    receipt_id = _record(path, cross_surface_recall="granted")[0]
    consent = _resolve(path)
    assert consent.cross_surface_recall is False
    assert consent.cross_surface_receipt_id == receipt_id


def test_d1_c11_concurrent_replacements_form_one_supersession_chain(tmp_path, monkeypatch) -> None:
    path = tmp_path / "state.db"
    root = _record(path, transcript_retention="granted")[0]
    ids = iter(("01JAAA00000000000000000001", "01JAAA00000000000000000002"))
    id_lock = threading.Lock()
    race = threading.Barrier(2)

    def racing_ulid() -> str:
        try:
            race.wait(timeout=0.2)
        except threading.BrokenBarrierError:
            pass
        with id_lock:
            return next(ids)

    monkeypatch.setattr(statedb.ulid, "new", racing_ulid)
    with ThreadPoolExecutor(max_workers=2) as pool:
        futures = [
            pool.submit(
                _record, path, _NOW + dt.timedelta(seconds=1), transcript_retention=decision
            )
            for decision in ("denied", "withdrawn")
        ]
        for future in futures:
            future.result()
    with sqlite3.connect(path) as conn:
        rows = dict(
            conn.execute(
                "SELECT receipt_id, supersedes FROM consent_receipts WHERE receipt_id != ?",
                (root,),
            )
        )
    assert set(rows) == {"01JAAA00000000000000000001", "01JAAA00000000000000000002"}
    predecessors = set(rows.values())
    assert root in predecessors
    assert len(predecessors) == 2
    assert predecessors - {root} <= set(rows)


def test_d1_c10_c15_policy_state_works_with_telemetry_off(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("DR_ALEX_TELEMETRY_OFF", "1")
    path = tmp_path / "state.db"
    owner = statedb.create_session_owner(
        "session-1",
        subject_id=_SUBJECT,
        actor_principal=_ACTOR,
        source=_SOURCE,
        now=_NOW,
        path=path,
    )
    _record(path, transcript_retention="granted")
    assert owner is not None
    assert _resolve(path).transcript_retention is True
    with sqlite3.connect(path) as conn:
        assert conn.execute("SELECT COUNT(*) FROM session_owners").fetchone()[0] == 1
        assert conn.execute("SELECT COUNT(*) FROM consent_receipts").fetchone()[0] == 1


def test_d1_c14_latest_grant_expired_resolves_to_deny(tmp_path) -> None:
    path = tmp_path / "state.db"
    consent = _consent(transcript_retention="granted")
    consent["expires_at"] = "2026-08-23T12:00:01Z"
    statedb.record_consent(
        subject_id=_SUBJECT,
        actor_principal=_ACTOR,
        source=_SOURCE,
        consent=consent,
        now=_NOW,
        path=path,
    )
    assert _resolve(path, _NOW + dt.timedelta(seconds=2)).transcript_retention is False


@pytest.fixture()
def client() -> TestClient:
    alexd._sessions.clear()
    return TestClient(alexd.app)


def _pair_token(client: TestClient) -> str:
    response = client.post("/pair", json={"code": pairing.create_pairing_code()})
    assert response.status_code == 200
    return response.json()["device_token"]


def _post(client: TestClient, endpoint: str, token: str, payload: dict[str, Any]):
    return client.post(endpoint, json=payload, headers={alexd.DEVICE_HEADER: token})


def _enable_consent(monkeypatch) -> None:
    monkeypatch.setenv("DR_ALEX_CONSENT_ENFORCEMENT", "1")
    monkeypatch.setenv("DR_ALEX_ALLOW_TEST_CONSENT", "1")


def _fake_model(monkeypatch, text: str = "synthetic reply") -> None:
    monkeypatch.setattr(
        llm,
        "generate",
        lambda messages, tier, **kwargs: llm.LLMResult(ok=True, text=text, tier=tier),
    )


def test_d1_i03_request_subject_fields_cannot_override_server_identity(client) -> None:
    token = _pair_token(client)
    response = _post(
        client,
        "/session/start",
        token,
        {
            "session_id": "owned-session",
            "subject_id": "spoofed",
            "actor_principal": "spoofed",
        },
    )
    assert response.status_code == 200
    owner = statedb.get_session_owner("owned-session")
    assert owner is not None
    assert owner.subject_id == pairing.local_subject_id()
    assert owner.subject_id != "spoofed"
    assert owner.actor_principal != "spoofed"


_SESSION_ENDPOINTS = (
    ("/turn", {"session_id": "{session}", "text": "synthetic hello"}),
    ("/checkin", {"session_id": "{session}"}),
    ("/session/end", {"session_id": "{session}"}),
)


@pytest.mark.parametrize(("endpoint", "payload"), _SESSION_ENDPOINTS)
def test_d1_i04_other_device_cannot_access_owned_session(client, endpoint, payload) -> None:
    owner_token, other_token = _pair_token(client), _pair_token(client)
    assert (
        _post(client, "/session/start", owner_token, {"session_id": "owned-session"}).status_code
        == 200
    )
    payload = {key: value.replace("{session}", "owned-session") for key, value in payload.items()}
    response = _post(client, endpoint, other_token, payload)
    assert response.status_code == 404
    assert response.json()["detail"] == "session_not_found"


@pytest.mark.parametrize(("endpoint", "payload"), _SESSION_ENDPOINTS)
def test_d1_i04_unowned_named_session_is_not_adopted(client, endpoint, payload) -> None:
    payload = {key: value.replace("{session}", "unowned-session") for key, value in payload.items()}
    response = _post(client, endpoint, _pair_token(client), payload)
    assert response.status_code == 404
    assert response.json()["detail"] == "session_not_found"


@pytest.mark.parametrize(
    ("endpoint", "payload"),
    (
        ("/session/start", {"session_id": "ended-session"}),
        ("/turn", {"session_id": "ended-session", "text": "synthetic hello"}),
        ("/checkin", {"session_id": "ended-session"}),
        ("/session/end", {"session_id": "ended-session"}),
    ),
)
def test_d1_i04_ended_session_is_not_reopened(client, endpoint, payload) -> None:
    token = _pair_token(client)
    assert (
        _post(client, "/session/start", token, {"session_id": "ended-session"}).status_code == 200
    )
    assert _post(client, "/session/end", token, {"session_id": "ended-session"}).status_code == 200
    owner = statedb.get_session_owner("ended-session")
    assert owner is not None and owner.ended_at is not None
    assert "ended-session" not in alexd._sessions
    response = _post(client, endpoint, token, payload)
    assert response.status_code == 404
    assert response.json()["detail"] == "session_not_found"


@pytest.mark.parametrize("endpoint", ("/turn", "/session/end"))
def test_d1_i04_missing_session_id_is_not_created(client, endpoint) -> None:
    response = _post(client, endpoint, _pair_token(client), {"text": "synthetic hello"})
    assert response.status_code == 404
    assert response.json()["detail"] == "session_not_found"


def test_d1_i04_checkin_without_id_creates_owned_session(client) -> None:
    token = _pair_token(client)
    response = _post(client, "/checkin", token, {})
    assert response.status_code == 200
    owner = statedb.get_session_owner(response.json()["session_id"])
    principal = pairing.resolve_device_token(token)
    assert owner is not None and principal is not None
    assert owner.actor_principal == principal.actor_principal


def test_d1_i04_generated_checkin_ids_do_not_collide(client) -> None:
    token = _pair_token(client)
    first = _post(client, "/checkin", token, {})
    second = _post(client, "/checkin", token, {})
    assert first.status_code == second.status_code == 200
    assert first.json()["session_id"] != second.json()["session_id"]


def test_d1_i04_session_id_cannot_smuggle_plaintext(client) -> None:
    marker = "SYNTHETIC CLINICAL BODY IN SESSION ID"
    response = _post(client, "/session/start", _pair_token(client), {"session_id": marker})
    assert response.status_code == 422
    assert response.json()["detail"] == "invalid_session_id"

    path = statedb.state_db_path()
    statedb.init_db(path)
    with pytest.raises(ValueError, match="invalid session id"):
        statedb.create_session_owner(
            marker,
            subject_id="subject",
            actor_principal="device:synthetic",
            source="pwa",
            path=path,
        )
    assert marker.encode() not in path.read_bytes()


def test_body_shaped_identifier_canaries_never_reach_plaintext_columns(client, monkeypatch) -> None:
    _enable_consent(monkeypatch)
    session_marker = "SYNTHETIC_CLINICAL_BODY_IN_SESSION_ID"
    copy_marker = "SYNTHETIC_CLINICAL_BODY_IN_COPY_VERSION"
    token = _pair_token(client)

    session_response = _post(
        client,
        "/session/start",
        token,
        {"session_id": session_marker},
    )
    consent = _consent(transcript_retention="granted")
    consent["copy_version"] = copy_marker
    consent_response = _post(client, "/session/start", token, {"consent": consent})

    assert session_response.status_code == 422
    assert session_response.json()["detail"] == "invalid_session_id"
    assert consent_response.status_code == 422
    assert consent_response.json()["detail"] == "invalid_consent_metadata"
    statedb.init_db()
    raw = statedb.state_db_path().read_bytes()
    assert session_marker.encode() not in raw
    assert copy_marker.encode() not in raw


def test_d1_i04_policy_store_failure_denies_session_access(client, monkeypatch) -> None:
    def unavailable(_session_id: str):
        raise sqlite3.OperationalError("synthetic policy-store failure")

    monkeypatch.setattr(statedb, "get_session_owner", unavailable)
    response = _post(
        client,
        "/turn",
        _pair_token(client),
        {"session_id": "owned-session", "text": "synthetic hello"},
    )
    assert response.status_code == 503
    assert response.json()["detail"] == "policy_state_unavailable"


@pytest.mark.parametrize(
    ("consent", "error"),
    (
        (_consent(transcript_retention="granted", surprise="granted"), "unknown_consent_key"),
        (_consent(transcript_retention="maybe"), "invalid_consent_decision"),
        (_consent(durable_memory="granted"), "durable_requires_transcript_retention"),
    ),
)
def test_d1_c03_c05_invalid_consent_is_http_422(client, monkeypatch, consent, error) -> None:
    _enable_consent(monkeypatch)
    response = _post(client, "/session/start", _pair_token(client), {"consent": consent})
    assert response.status_code == 422
    assert response.json()["detail"] == error


@pytest.mark.parametrize("decision", ([], {}))
def test_d1_c04_non_scalar_consent_decision_is_http_422(client, monkeypatch, decision) -> None:
    _enable_consent(monkeypatch)
    response = _post(
        client,
        "/session/start",
        _pair_token(client),
        {"consent": _consent(transcript_retention=decision)},
    )
    assert response.status_code == 422
    assert response.json()["detail"] == "invalid_consent_decision"


@pytest.mark.parametrize(
    ("field", "value", "error"),
    (
        ("policy_version", "1." * 16 + "1", "invalid_policy_version"),
        ("copy_version", "a" * 129, "invalid_consent_metadata"),
        ("locale", "en" + "-AA" * 12, "invalid_locale"),
        ("effective_at", "2026-08-23T18:00:00" + "0" * 20 + "Z", "invalid_effective_at"),
    ),
)
def test_d1_c04_oversized_consent_metadata_is_http_422(
    client, monkeypatch, field, value, error
) -> None:
    _enable_consent(monkeypatch)
    consent = _consent(transcript_retention="granted")
    consent[field] = value
    response = _post(client, "/session/start", _pair_token(client), {"consent": consent})
    assert response.status_code == 422
    assert response.json()["detail"] == error


def test_d1_c04_consent_write_failure_rolls_back_session_creation(client, monkeypatch) -> None:
    _enable_consent(monkeypatch)
    token, session_id = _pair_token(client), "atomic-policy-failure"
    path = statedb.state_db_path()
    statedb.init_db(path)
    with sqlite3.connect(path) as conn:
        conn.execute(
            "CREATE TRIGGER fail_synthetic_consent BEFORE INSERT ON consent_receipts "
            "BEGIN SELECT RAISE(ABORT, 'synthetic consent failure'); END"
        )
    response = _post(
        client,
        "/session/start",
        token,
        {"session_id": session_id, "consent": _consent(transcript_retention="granted")},
    )
    assert response.status_code == 503
    assert response.json()["detail"] == "consent_store_unavailable"
    assert session_id not in alexd._sessions
    with sqlite3.connect(path) as conn:
        assert (
            conn.execute(
                "SELECT COUNT(*) FROM session_owners WHERE session_id = ?", (session_id,)
            ).fetchone()[0]
            == 0
        )


def test_d1_c06_absent_api_consent_denies_when_enforcement_is_on(client, monkeypatch) -> None:
    monkeypatch.setenv("DR_ALEX_CONSENT_ENFORCEMENT", "1")
    response = _post(client, "/session/start", _pair_token(client), {})
    assert response.status_code == 200
    assert response.json()["consent_status"] == {
        "transcript_retention": "denied",
        "durable_memory": "denied",
        "cross_surface_recall": "denied",
    }
    assert response.json()["consent_active"] is False


def test_d1_c11_consent_input_conflicts_when_enforcement_is_off(client) -> None:
    response = _post(
        client,
        "/session/start",
        _pair_token(client),
        {"consent": _consent(transcript_retention="denied")},
    )
    assert response.status_code == 409
    assert response.json()["detail"] == "consent_feature_disabled"


def test_d1_c12_test_consent_requires_approved_channel(client, monkeypatch) -> None:
    monkeypatch.setenv("DR_ALEX_CONSENT_ENFORCEMENT", "1")
    response = _post(
        client,
        "/session/start",
        _pair_token(client),
        {"consent": _consent(transcript_retention="granted")},
    )
    assert response.status_code == 403
    assert response.json()["detail"] == "consent_channel_not_approved"


def test_d1_c13_room_javascript_has_no_consent_grant() -> None:
    assert "granted" not in (alexd.ROOM_DIR / "app.js").read_text(encoding="utf-8")


def _start_and_turn(
    client: TestClient,
    monkeypatch,
    *,
    consent: dict[str, Any] | None = None,
    text: str = "synthetic hello",
    fake_model: bool = True,
) -> str:
    _enable_consent(monkeypatch)
    if fake_model:
        _fake_model(monkeypatch)
    token = _pair_token(client)
    start = _post(client, "/session/start", token, {"consent": consent} if consent else {})
    session_id = start.json()["session_id"]
    response = _post(client, "/turn", token, {"session_id": session_id, "text": text})
    assert response.status_code == 200
    return session_id


def test_d1_t01_retention_grant_writes_only_encrypted_transcript_bodies(
    client, monkeypatch
) -> None:
    marker = "SYNTHETIC_GRANTED_BODY"
    session_id = _start_and_turn(
        client,
        monkeypatch,
        consent=_consent(transcript_retention="granted"),
        text=marker,
    )
    assert [turn.body for turn in statedb.load_transcript(session_id)] == [
        marker,
        "synthetic reply",
    ]
    assert marker.encode() not in statedb.state_db_path().read_bytes()


def test_d1_t02_message_receipt_without_consent_keeps_trace_but_no_body(
    client, monkeypatch
) -> None:
    monkeypatch.setattr(statedb, "record_transcript", lambda **kwargs: pytest.fail("body write"))
    session_id = _start_and_turn(client, monkeypatch)
    assert statedb.load_transcript(session_id) == []
    with sqlite3.connect(statedb.state_db_path()) as conn:
        assert (
            conn.execute(
                "SELECT COUNT(*) FROM turn_traces WHERE session_id=?", (session_id,)
            ).fetchone()[0]
            == 1
        )


def test_d1_t03_legacy_engine_caller_still_retains_by_default(monkeypatch) -> None:
    _fake_model(monkeypatch, "legacy reply")
    engine.run_turn("legacy synthetic body", session_id="legacy-session")
    assert [turn.body for turn in statedb.load_transcript("legacy-session")] == [
        "legacy synthetic body",
        "legacy reply",
    ]


def test_d1_t04_transcript_failure_returns_turn_with_class_only_warning(
    monkeypatch, caplog
) -> None:
    marker = "SYNTHETIC_FAILURE_BODY"
    _fake_model(monkeypatch, "reply")
    monkeypatch.setattr(
        statedb,
        "record_transcript",
        lambda **kwargs: (_ for _ in ()).throw(sqlite3.OperationalError(marker)),
    )
    with caplog.at_level(logging.WARNING, logger="dr_alex.engine"):
        outcome = engine.run_turn("synthetic hello", transcript_policy="retain")
    assert outcome.text == "reply"
    assert "OperationalError" in caplog.text
    assert marker not in caplog.text


@pytest.mark.parametrize(("decision", "expected_rows"), (("denied", 0), ("granted", 2)))
def test_d1_t05_t06_red_respects_retention_without_model_or_retrieval(
    client, monkeypatch, decision, expected_rows
) -> None:
    monkeypatch.setattr(
        engine, "retrieve_context", lambda *args, **kwargs: pytest.fail("RED reached retrieval")
    )
    monkeypatch.setattr(llm, "generate", lambda *args, **kwargs: pytest.fail("RED reached model"))
    session_id = _start_and_turn(
        client,
        monkeypatch,
        consent=_consent(transcript_retention=decision),
        text="I want to kill myself",
        fake_model=False,
    )
    assert len(statedb.load_transcript(session_id)) == expected_rows
    assert alexd._sessions[session_id].history == []


def test_d1_t07_end_rechecks_deny_before_draining_pending_fragment(client, monkeypatch) -> None:
    _enable_consent(monkeypatch)
    _fake_model(monkeypatch, "reply")
    token = _pair_token(client)
    session_id = _post(
        client,
        "/session/start",
        token,
        {"consent": _consent(transcript_retention="granted")},
    ).json()["session_id"]
    _post(
        client,
        "/turn",
        token,
        {"session_id": session_id, "text": "pending fragment", "fragment": True},
    )
    monkeypatch.setattr(
        statedb, "resolve_consent", lambda *args, **kwargs: statedb.EffectiveConsent()
    )
    response = _post(client, "/session/end", token, {"session_id": session_id})
    assert response.status_code == 200
    assert statedb.load_transcript(session_id) == []


def test_rc4_r01_expired_consent_is_rechecked_before_end_drain(client, monkeypatch, caplog) -> None:
    _enable_consent(monkeypatch)
    _fake_model(monkeypatch, "synthetic reply")
    before_expiry = dt.datetime(2026, 8, 23, 12, 0, tzinfo=dt.UTC)
    after_expiry = before_expiry + dt.timedelta(seconds=2)
    expired = False
    resolve_consent = statedb.resolve_consent

    def resolve(subject_id, source, **kwargs):
        return resolve_consent(
            subject_id,
            source,
            now=after_expiry if expired else before_expiry,
            **kwargs,
        )

    monkeypatch.setattr(statedb, "resolve_consent", resolve)
    token = _pair_token(client)
    consent = _consent(
        transcript_retention="granted",
        durable_memory="granted",
    )
    consent.update(
        effective_at="2026-08-23T11:59:00Z",
        expires_at="2026-08-23T12:00:01Z",
    )
    session_id = _post(
        client,
        "/session/start",
        token,
        {"consent": consent},
    ).json()["session_id"]
    _post(
        client,
        "/turn",
        token,
        {"session_id": session_id, "text": "synthetic pending fragment", "fragment": True},
    )
    expired = True

    with caplog.at_level(logging.INFO, logger="dr_alex.trace"):
        response = _post(client, "/session/end", token, {"session_id": session_id})

    assert response.status_code == 200
    assert response.json()["finalization"]["status"] == "closed_transient"
    assert statedb.load_transcript(session_id) == []
    assert "event=transcript_retention source=pwa status=skipped skipped_count=2" in caplog.text


def test_section16_denial_logs_are_body_free(client, caplog) -> None:
    owner_token = _pair_token(client)
    other_token = _pair_token(client)
    session_id = _post(client, "/session/start", owner_token, {}).json()["session_id"]
    owner = statedb.get_session_owner(session_id)
    assert owner is not None

    with caplog.at_level(logging.INFO, logger="dr_alex.alexd"):
        mismatch = _post(client, "/session/end", other_token, {"session_id": session_id})
        denied = client.post(
            "/session/end",
            json={"session_id": session_id},
            headers={alexd.DEVICE_HEADER: "synthetic-invalid-device-token"},
        )

    assert mismatch.status_code == 404
    assert denied.status_code == 401
    assert "event=owner_mismatch source=pwa count=1" in caplog.text
    assert "event=authorization_denial source=pwa count=1" in caplog.text
    assert session_id not in caplog.text
    assert owner.subject_id not in caplog.text
    assert owner.actor_principal not in caplog.text
    assert owner_token not in caplog.text
    assert other_token not in caplog.text


def test_retention_withdrawal_during_model_call_blocks_transcript_persistence(
    client, monkeypatch
) -> None:
    _enable_consent(monkeypatch)
    model_started = threading.Event()
    release_model = threading.Event()

    def blocking_model(messages, tier, **kwargs):
        model_started.set()
        assert release_model.wait(timeout=5)
        return llm.LLMResult(ok=True, text="synthetic reply", tier=tier)

    monkeypatch.setattr(llm, "generate", blocking_model)
    token = _pair_token(client)
    start = _post(
        client,
        "/session/start",
        token,
        {"consent": _consent(transcript_retention="granted")},
    )
    session_id = start.json()["session_id"]
    owner = statedb.get_session_owner(session_id)
    assert owner is not None

    with ThreadPoolExecutor(max_workers=1) as pool:
        turn = pool.submit(
            _post,
            client,
            "/turn",
            token,
            {"session_id": session_id, "text": "synthetic in-flight body"},
        )
        assert model_started.wait(timeout=5)
        statedb.record_consent(
            subject_id=owner.subject_id,
            actor_principal=owner.actor_principal,
            source=owner.source,
            consent=_consent(transcript_retention="withdrawn"),
        )
        release_model.set()
        response = turn.result(timeout=5)

    assert response.status_code == 200
    assert statedb.load_transcript(session_id) == []
    with sqlite3.connect(statedb.state_db_path()) as conn:
        assert (
            conn.execute(
                "SELECT COUNT(*) FROM turn_traces WHERE session_id=?", (session_id,)
            ).fetchone()[0]
            == 1
        )


def test_turn_does_not_recreate_missing_live_session(client, monkeypatch) -> None:
    _enable_consent(monkeypatch)
    model_called = False

    def model(messages, tier, **kwargs):
        nonlocal model_called
        model_called = True
        return llm.LLMResult(ok=True, text="synthetic reply", tier=tier)

    monkeypatch.setattr(llm, "generate", model)
    token = _pair_token(client)
    session_id = _post(client, "/session/start", token, {}).json()["session_id"]
    alexd._sessions.pop(session_id)

    response = _post(
        client,
        "/turn",
        token,
        {"session_id": session_id, "text": "synthetic post-restart turn"},
    )

    assert response.status_code == 404
    assert response.json()["detail"] == "session_not_found"
    assert session_id not in alexd._sessions
    assert model_called is False


def test_end_rejects_owner_bound_to_noncanonical_subject(client) -> None:
    token = _pair_token(client)
    principal = pairing.resolve_device_token(token)
    assert principal is not None
    session_id = "foreign-subject-session"
    statedb.create_session_owner(
        session_id,
        subject_id="foreign-subject",
        actor_principal=principal.actor_principal,
        source="pwa",
    )
    alexd._sessions[session_id] = alexd.RoomSession(session_id, test_traffic=True)

    response = _post(client, "/session/end", token, {"session_id": session_id})

    assert response.status_code == 404
    assert response.json()["detail"] == "session_not_found"


def test_d1_c15_corrupt_policy_store_unhealthy_when_telemetry_off(tmp_path, monkeypatch) -> None:
    path = tmp_path / "state.db"
    path.write_bytes(b"not-sqlite")
    monkeypatch.setenv("DR_ALEX_TELEMETRY_OFF", "1")
    assert statedb.healthy(path) is False


def test_d1_c08_supersedes_follows_instant_not_text_order(tmp_path) -> None:
    path = tmp_path / "state.db"
    later = _record(
        path, transcript_retention="granted", effective_at="2026-08-23T12:00:00.500000Z"
    )[0]
    _record(path, transcript_retention="denied", effective_at="2026-08-23T12:00:00Z")
    newest = _record(path, transcript_retention="withdrawn", effective_at="2026-08-23T12:00:01Z")[0]
    with sqlite3.connect(path) as conn:
        prior = conn.execute(
            "SELECT supersedes FROM consent_receipts WHERE receipt_id=?", (newest,)
        ).fetchone()[0]
    assert prior == later


def test_d1_i_pairing_success_log_omits_device_id(caplog) -> None:
    with caplog.at_level(logging.INFO, logger="dr_alex.pairing"):
        device = _paired_device()
    assert device.id not in caplog.text
