from duck_brain.safety import SafetyLayer

CFG = {
    "stop_words": ["stop", "duck stop", "freeze"],
    "max_gestures_per_turn": 3,
    "max_times": 3,
    "max_hold_s": 10,
    "head_limits": {"head_yaw": [-60, 60], "head_pitch": [-60, 45], "head_roll": [-20, 20]},
}


def layer() -> SafetyLayer:
    s = SafetyLayer(CFG)
    s.expressions = ["neutral", "happy", "grumpy"]
    return s


def test_full_spin_is_clamped_with_reason():
    plan = layer().review({"say": "Wheee", "expression": "happy",
                           "gestures": [{"tool": "look_at", "args": {"yaw": 360, "pitch": 0}}]})
    g = plan.gestures[0]
    assert g.status == "clamped"
    assert g.args["yaw"] == 60
    assert any("full spin" in r for r in g.reasons)


def test_unknown_tool_is_blocked():
    plan = layer().review({"say": "", "expression": "happy",
                           "gestures": [{"tool": "walk_forward", "args": {"seconds": 5}}]})
    assert plan.gestures[0].status == "blocked"
    assert plan.gestures[0].tool is None


def test_times_and_hold_are_capped():
    plan = layer().review({"say": "", "expression": "happy", "gestures": [
        {"tool": "nod", "args": {"times": 50}},
        {"tool": "look_at", "args": {"yaw": 0, "pitch": 0, "hold_s": 9999}},
    ]})
    assert plan.gestures[0].args["times"] == 3
    assert plan.gestures[1].args["_hold_s"] == 10
    assert all(g.status == "clamped" for g in plan.gestures)


def test_too_many_gestures_blocked():
    plan = layer().review({"say": "", "expression": "happy",
                           "gestures": [{"tool": "nod"}] * 5})
    assert [g.status for g in plan.gestures] == ["ok", "ok", "ok", "blocked", "blocked"]


def test_unknown_expression_falls_back_to_neutral():
    plan = layer().review({"say": "hi", "expression": "furious", "gestures": []})
    assert plan.expression.args["name"] == "neutral"
    assert plan.expression.status == "clamped"


def test_non_numeric_args_blocked():
    plan = layer().review({"say": "", "expression": "happy",
                           "gestures": [{"tool": "tilt_head", "args": {"angle": "lots"}}]})
    assert plan.gestures[0].status == "blocked"


def test_stop_words():
    s = layer()
    assert s.is_stop("Duck, STOP!")
    assert s.is_stop("freeze")
    assert not s.is_stop("don't stopper the bottle")
    assert not s.is_stop("tell me a story")


def test_ear_and_lamp_gestures_get_fixed_args():
    s = layer()
    plan = s.review({"say": "hi", "expression": "happy", "gestures": [
        {"tool": "wiggle_ears", "args": {"times": 9}},
        {"tool": "lamp_on", "args": {"on": False}},
    ]})
    wiggle, lamp = plan.gestures
    assert wiggle.tool == "ears_gesture" and wiggle.args == {"times": 3, "name": "wiggle"}
    assert wiggle.status == "clamped"
    assert lamp.tool == "lamp_set" and lamp.args == {"on": True}
