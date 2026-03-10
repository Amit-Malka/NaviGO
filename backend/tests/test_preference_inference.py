from app.agent.nodes import _infer_preference_facts_from_text


def _fact_value(facts: list[dict], key: str) -> str | None:
    for fact in facts:
        if fact.get("pref_key") == key:
            return fact.get("pref_value")
    return None


def test_infers_cheapest_preference():
    facts = _infer_preference_facts_from_text("I always prefer the cheapest ticket option.")
    assert _fact_value(facts, "price_priority") == "cheapest"


def test_infers_duration_and_stops_preferences():
    facts = _infer_preference_facts_from_text("Please find the shortest nonstop flight.")
    assert _fact_value(facts, "time_priority") == "shortest_duration"
    assert _fact_value(facts, "stops_priority") == "direct_only"

