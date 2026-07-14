"""Protected-reveal contract: a Shorts batch may AIM at the parent's biggest payoff but
never consume it — otherwise the batch collectively spoils the full video's best moment
and the Short->main funnel dies."""

import json

from ai_operator.content import short_script_generator as gen


def _parent(scores):
    return {
        "payoff_nodes": [
            {"text": f"payoff-{s}-{i}", "surprise_score": s} for i, s in enumerate(scores)
        ],
        "shot_list": [{"keywords": ["harbor"]}],
        "narration": "n",
    }


def test_distill_reserves_top_payoff_as_protected_reveal():
    facts = json.loads(gen._distill_parent(_parent([5, 4, 3])))
    assert facts["protected_reveal"]["surprise_score"] == 5
    assert facts["protected_reveal"] not in facts["top_payoffs"]
    assert [p["surprise_score"] for p in facts["top_payoffs"]] == [4, 3]


def test_single_payoff_parent_keeps_it_buildable():
    # nothing to protect without starving the batch of material
    facts = json.loads(gen._distill_parent(_parent([4])))
    assert facts["protected_reveal"] is None
    assert [p["surprise_score"] for p in facts["top_payoffs"]] == [4]


def test_system_prompt_carries_funnel_directives():
    # config-lock: the curiosity-funnel directives must survive future prompt edits
    for marker in ("protected_reveal", "EFFECT-FIRST", "LOOP ENDING"):
        assert marker in gen._SYSTEM, f"missing directive marker: {marker}"
