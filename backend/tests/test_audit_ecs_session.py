import uuid

import pytest

from app.services.audit_ecs import session_event

TYPES = {"launch": "start", "connect": "start", "stop": "end",
         "disconnect": "end", "lock": "change", "unlock": "change"}


@pytest.mark.parametrize("verb,etype", TYPES.items())
def test_each_action(verb, etype):
    ev = session_event(f"session.{verb}", session_id="s1", kind="instance")
    assert ev["event"]["action"] == f"session.{verb}"
    assert ev["event"]["dataset"] == "styx.audit"
    assert ev["event"]["category"] == ["session"]
    assert ev["event"]["type"] == [etype]
    assert ev["event"]["outcome"] == "success"
    assert uuid.UUID(ev["event"]["id"]).version == 4
    assert ev["ecs"]["version"]
    assert ev["styx"]["session"] == {"id": "s1", "kind": "instance"}


def test_full_fields_and_pruning():
    ev = session_event("session.stop", session_id="w1", kind="workstation", user_id="u1",
                       user_name="ann", reason="idle", viewer_id="v1",
                       image_digest="sha256:abc", node="n1", groups=["a", "b"])
    assert ev["styx"]["session"] == {"id": "w1", "kind": "workstation", "reason": "idle",
                                     "viewer_id": "v1", "groups": ["a", "b"]}
    assert ev["container"]["image"]["hash"]["all"] == ["sha256:abc"]
    assert ev["host"]["name"] == "n1"
    assert ev["user"] == {"id": "u1", "name": "ann"}
    bare = session_event("session.lock", session_id="s", kind="instance")
    assert "user" not in bare and "host" not in bare and "container" not in bare


def test_unknown_action():
    with pytest.raises(ValueError):
        session_event("session.nope", session_id="s", kind="instance")
