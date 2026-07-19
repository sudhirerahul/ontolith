"""
Tests for the Retail Roleplay Studio generator (playbook/roleplay_generator.py).
Runs entirely against the deterministic template path (no OPENROUTER_API_KEY in test env).
"""
from callguard_ai.playbook.roleplay_generator import RoleplayStudio
from callguard_ai.playbook.parsers import extract_headings

PLAYBOOK_TEXT = """
1. MATTRESSES
Discovery first, then recommend.

2. FINANCING
Ask why before pitching a plan.

3. DELIVERY DELAYS
Acknowledge frustration first.
"""

OBJECTIONS_TEXT = '- financing: "I don\'t want another monthly payment."\n'


def test_extract_headings_finds_numbered_sections():
    headings = extract_headings(PLAYBOOK_TEXT)
    assert "Mattresses" in headings
    assert "Financing" in headings
    assert "Delivery Delays" in headings


def test_generate_produces_requested_count_with_unique_ids():
    studio = RoleplayStudio(
        retailer="Test Retailer",
        playbook_text=PLAYBOOK_TEXT,
        objections_text=OBJECTIONS_TEXT,
    )
    roleplay_set, scenarios = studio.generate(count=15)

    assert len(scenarios) == 15
    assert len(set(s.scenario_id for s in scenarios)) == 15
    assert roleplay_set.llm_powered is False  # no API key in test environment
    assert roleplay_set.metadata["scenario_count"] == 15


def test_generated_scenarios_are_valid_retail_scenarios():
    studio = RoleplayStudio(
        retailer="Test Retailer",
        playbook_text=PLAYBOOK_TEXT,
        objections_text=OBJECTIONS_TEXT,
    )
    _roleplay_set, scenarios = studio.generate(count=10)

    for s in scenarios:
        assert s.category == "retail_sales"
        assert s.source == "playbook"
        assert len(s.conversation_steps) == 3
        assert s.difficulty in ("low", "medium", "high", "expert")
        assert s.objection_chain  # always has exactly one tag
        assert s.persona_profile.get("persona_id")


def test_financing_scenario_uses_the_supplied_objection_quote():
    studio = RoleplayStudio(
        retailer="Test Retailer",
        playbook_text=PLAYBOOK_TEXT,
        objections_text=OBJECTIONS_TEXT,
    )
    _roleplay_set, scenarios = studio.generate(count=20)
    financing_scenarios = [s for s in scenarios if s.objection_chain == ["financing"]]

    assert financing_scenarios
    assert financing_scenarios[0].conversation_steps[0].user == "I don't want another monthly payment."
