from audit import (
    ACTION_ACCOUNT_CREATE,
    ACTION_DM_SEND,
    ACTION_LOGIN_SUCCESS,
    CATEGORY_ACCOUNTS,
    CATEGORY_AUTH,
    CATEGORY_DIRECT_MESSAGES,
    sanitize_metadata,
)


def test_audit_sanitizer_drops_sensitive_keys_and_controls():
    cleaned = sanitize_metadata(
        {
            "username": "operator",
            "password": "must-not-be-stored",
            "nested": {"token": "secret", "note": "ok\x00value"},
            "long": "x" * 500,
        }
    )

    assert cleaned["username"] == "operator"
    assert "password" not in cleaned
    assert "token" not in cleaned["nested"]
    assert "\x00" not in cleaned["nested"]["note"]
    assert len(cleaned["long"]) == 256


def test_audit_events_are_append_only_through_api(client, login, account_service):
    csrf_token = login()
    account_service.create_account(
        actor_session={"role": "superadmin", "username": "root"},
        username="newmod",
        password="newmod-password",
        role="moderator",
    )

    created = client.get("/api/audit-logs?page_size=100").get_json()
    event_ids = [event["id"] for event in created["events"]]
    assert event_ids

    delete_response = client.delete(
        f"/api/audit-logs/{event_ids[0]}",
        headers={"X-CSRF-Token": csrf_token},
    )
    # There is deliberately no delete API; it falls through to the SPA route.
    assert delete_response.status_code in (404, 405)

    after = client.get("/api/audit-logs?page_size=100").get_json()
    assert [event["id"] for event in after["events"]] == event_ids


def test_audit_pagination_and_ordering(client, login, account_service):
    login()
    for index in range(4):
        account_service.create_account(
            actor_session={"role": "superadmin", "username": "root"},
            username=f"mod{index}",
            password="moderator-password",
            role="moderator",
        )

    first_page = client.get("/api/audit-logs?page=1&page_size=2").get_json()
    second_page = client.get("/api/audit-logs?page=2&page_size=2").get_json()

    assert first_page["total"] >= 5
    assert first_page["pages"] >= 2
    assert len(first_page["events"]) == 2
    assert len(second_page["events"]) == 2
    assert first_page["events"][0]["id"] > second_page["events"][0]["id"]

    timestamps = [event["created_at"] for event in first_page["events"]]
    assert timestamps == sorted(timestamps, reverse=True)


def test_audit_filters_by_category_action_actor_and_query(client, login):
    login()

    auth_only = client.get("/api/audit-logs?category=auth").get_json()
    assert auth_only["events"]
    assert all(event["category"] == CATEGORY_AUTH for event in auth_only["events"])

    action_only = client.get(
        f"/api/audit-logs?action={ACTION_LOGIN_SUCCESS}"
    ).get_json()
    assert action_only["events"]
    assert all(event["action"] == ACTION_LOGIN_SUCCESS for event in action_only["events"])

    actor_only = client.get("/api/audit-logs?actor=root").get_json()
    assert actor_only["events"]
    assert all(event["actor_username"] == "root" for event in actor_only["events"])

    search = client.get("/api/audit-logs?query=root").get_json()
    assert search["events"]


def test_audit_detail_endpoint(client, login):
    login()
    listing = client.get("/api/audit-logs?page_size=1").get_json()
    event_id = listing["events"][0]["id"]

    response = client.get(f"/api/audit-logs/{event_id}")

    assert response.status_code == 200
    event = response.get_json()["event"]
    assert event["id"] == event_id
    assert isinstance(event["metadata"], dict)


def test_audit_meta_lists_actions_and_categories(client, login):
    login()
    response = client.get("/api/audit-logs/meta")

    assert response.status_code == 200
    body = response.get_json()
    values = {item["value"] for item in body["categories"]}
    assert CATEGORY_AUTH in values
    assert CATEGORY_ACCOUNTS in values
    assert CATEGORY_DIRECT_MESSAGES in values
    action_values = {item["value"] for item in body["actions"]}
    assert ACTION_ACCOUNT_CREATE in action_values
    assert ACTION_DM_SEND in action_values


def test_audit_rejects_invalid_filters(client, login):
    login()

    assert client.get("/api/audit-logs?category=invalid").status_code == 400
    assert client.get("/api/audit-logs?page=0").status_code == 400
    assert client.get("/api/audit-logs?page_size=1000").status_code == 400
    assert client.get("/api/audit-logs?from=not-a-date").status_code == 400
    assert client.get("/api/audit-logs?query=" + "x" * 201).status_code == 400


def test_audit_records_dm_send_without_message_content(client, login, account_service, audit_service):
    csrf_token = login()
    client.post(
        "/api/direct-messages/send",
        data={"user_id": "223456789012345678", "content": "top secret message"},
        headers={"X-CSRF-Token": csrf_token},
    )

    events = audit_service.list_events(page=1, page_size=10)["events"]
    dm_events = [event for event in events if event["action"] == ACTION_DM_SEND]
    assert dm_events
    serialized = str(dm_events[0]["metadata"])
    assert "top secret message" not in serialized
    assert dm_events[0]["target_type"] == "dm_user"
    assert dm_events[0]["target_id"] == "223456789012345678"
