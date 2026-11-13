"""Kibana saved objects as code (styx-portal#223): session timeline."""
import json
from pathlib import Path

NDJSON = (
    Path(__file__).resolve().parents[2]
    / "deploy" / "logging" / "kibana" / "session-timeline.ndjson"
)
COLUMNS = ["user.name", "event.action", "styx.session.id", "styx.session.reason", "host.name"]


def _objects():
    lines = [ln for ln in NDJSON.read_text().splitlines() if ln.strip()]
    return [json.loads(ln) for ln in lines]


def _by_type(t):
    return [o for o in _objects() if o["type"] == t]


def test_every_line_is_json_with_id_and_type():
    objs = _objects()
    assert len(objs) == 2
    for o in objs:
        assert o["id"] and o["type"] and o["attributes"]


def test_data_view_targets_audit_dataset():
    (dv,) = _by_type("index-pattern")
    assert dv["attributes"]["title"] == "logs-styx.audit-*"
    assert dv["attributes"]["timeFieldName"] == "@timestamp"


def test_saved_search_query_sort_columns():
    (dv,) = _by_type("index-pattern")
    (s,) = _by_type("search")
    a = s["attributes"]
    assert a["title"] == "Styx session timeline"
    assert a["columns"] == COLUMNS
    assert a["sort"] == [["@timestamp", "asc"]]
    src = json.loads(a["kibanaSavedObjectMeta"]["searchSourceJSON"])
    assert src["query"] == {"language": "kuery", "query": "event.category: session"}
    assert src["indexRefName"] == "kibanaSavedObjectMeta.searchSourceJSON.index"
    (ref,) = s["references"]
    assert ref == {
        "id": dv["id"],
        "name": "kibanaSavedObjectMeta.searchSourceJSON.index",
        "type": "index-pattern",
    }
