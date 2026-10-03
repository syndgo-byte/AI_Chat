import json
from concurrent.futures import ThreadPoolExecutor

import pytest

from ai_chat import AutoSendLearner


def test_default_gate(tmp_path):
    learner = AutoSendLearner(tmp_path / "config.json")
    assert learner.should_send({"route": "auto", "ai_confidence": 0.8})
    for confidence in (None, "0.9", True, float("nan"), float("inf"), 1.1, 0.79):
        assert not learner.should_send({"route": "auto", "ai_confidence": confidence})
    assert not learner.should_send({"route": "approve", "ai_confidence": 1})
    assert not learner.should_send({})


def test_consecutive_and_repeated_feedback(tmp_path):
    path = tmp_path / "config.json"
    learner = AutoSendLearner(path)
    for cid in range(1, 4):
        learner.record(cid, True)
        learner.record(cid, True, {"useful": False, "satisfaction": 0.3})
    assert learner.rules["min_confidence"] == 0.7
    assert learner.rules["last_update"]
    learner = AutoSendLearner(path)
    for _ in range(4):
        learner.record(3, True, {"useful": False, "satisfaction": 0.3})
    assert len(learner.rules["history"]) == 3
    assert learner.rules["min_confidence"] == 0.7
    for cid in range(4, 16):
        learner.record(cid, True, {"satisfaction": 0.1})
    assert learner.rules["min_confidence"] == 0.5


def test_seven_of_ten_and_no_feedback_not_negative(tmp_path):
    learner = AutoSendLearner(tmp_path / "config.json")
    learner.rules["consecutive_threshold"] = 10
    learner.save()
    for cid, useful in enumerate([False, False, True, False, False, True, False, False, True, False], 1):
        learner.record(cid, True, {"useful": useful})
    assert learner.rules["min_confidence"] == 0.7
    for cid in range(11, 25):
        learner.record(cid, True)
    assert learner.rules["min_confidence"] == 0.7


def test_atomic_updates_from_independent_instances(tmp_path):
    path = tmp_path / "nested" / "config.json"
    learners = [AutoSendLearner(path) for _ in range(20)]
    with ThreadPoolExecutor(max_workers=4) as pool:
        list(pool.map(lambda pair: pair[1].record(pair[0] + 1, True), enumerate(learners)))
    assert len(AutoSendLearner(path).rules["history"]) == 20
    assert not list(path.parent.glob("*.tmp"))


def test_history_limit_and_legacy_defaults(tmp_path):
    path = tmp_path / "config.json"
    path.write_text(json.dumps({"min_confidence": 0.9, "history": [
        {"complaint_id": i, "sent": True, "feedback": {}} for i in range(1, 1002)]}))
    learner = AutoSendLearner(path)
    learner.record(1002, True)
    assert len(learner.rules["history"]) == 1000
    assert learner.rules["history"][0]["complaint_id"] == 3
    assert learner.rules["requires_route_auto"] is True


@pytest.mark.parametrize("data", ["{", "[]", '{"min_confidence": null}', '{"history": [null]}'])
def test_bad_config_uses_defaults(tmp_path, data):
    path = tmp_path / "config.json"
    path.write_text(data)
    assert AutoSendLearner(path).rules["min_confidence"] == 0.8


@pytest.mark.parametrize("feedback", [{"useful": "false"}, {"satisfaction": True},
    {"satisfaction": -0.1}, {"satisfaction": 1.1}, {"satisfaction": float("nan")}])
def test_invalid_feedback_not_saved(tmp_path, feedback):
    path = tmp_path / "config.json"
    learner = AutoSendLearner(path)
    with pytest.raises(ValueError):
        learner.record(1, True, feedback)
    assert not path.exists()
