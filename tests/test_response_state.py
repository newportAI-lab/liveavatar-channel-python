from liveavatar_channel_sdk import ResponseStateEvent


def test_response_state_event_preserves_unknown_protocol_values():
    event = ResponseStateEvent(
        session_id="session-1",
        request_id="request-1",
        response_id="response-1",
        seq=17,
        timestamp=1788960000000,
        state="FUTURE_STATE",
        reason="FUTURE_REASON",
    )

    assert event.state == "FUTURE_STATE"
    assert event.reason == "FUTURE_REASON"
    assert event.session_id == "session-1"
    assert event.request_id == "request-1"
    assert event.response_id == "response-1"
    assert event.seq == 17
    assert event.timestamp == 1788960000000
