"""
Retail Roleplay Studio — turns a retailer's playbook/catalog/methodology/objections/brand
tone into a set of persona-driven, objection-tree-organized Scenario YAMLs.

Deterministic template path (no API key) always produces a full, runnable, catalog-grounded
scenario set. When OPENROUTER_API_KEY is set, the first `llm_enhance_limit` scenarios get
LLM-authored dialogue grounded in the actual playbook text (same raw-urllib OpenRouter call
style as scenarios/dynamic_generator.py) — this keeps runtime/cost bounded even when
generating 100+ scenarios while still demonstrating the LLM-enhanced path.
"""
from __future__ import annotations
import json
import os
import re
import urllib.error
import urllib.request
from datetime import datetime, timezone
from itertools import cycle
from typing import Any

from ..models.scenario import ConversationStep, Expected, PassCriteria, Scenario, Thresholds
from ..models.persona import CustomerPersona, ObjectionNode, ProductHierarchy, RoleplaySet
from ..utils.slug import slugify
from .parsers import extract_headings

PERSONA_ARCHETYPES: list[dict[str, Any]] = [
    {"persona_id": "budget_conscious", "name": "Budget-Conscious Shopper",
     "motivation": "Wants the best value without overspending", "budget_sensitivity": "high",
     "tone": "cautious", "objections": ["financing", "competitor_pricing"]},
    {"persona_id": "first_time_couple", "name": "Couple Buying First Home",
     "motivation": "Furnishing a first home together, nervous about big purchases",
     "budget_sensitivity": "high", "tone": "earnest", "objections": ["financing", "warranty"]},
    {"persona_id": "luxury_buyer", "name": "Luxury Buyer",
     "motivation": "Wants the best available; price is secondary to quality",
     "budget_sensitivity": "low", "tone": "confident", "objections": ["competitor_pricing", "warranty"]},
    {"persona_id": "skeptical_warranty", "name": "Skeptical Warranty Customer",
     "motivation": "Was burned by fine print before, doesn't trust sales claims",
     "budget_sensitivity": "medium", "tone": "guarded", "objections": ["warranty", "protection_plan"]},
    {"persona_id": "frustrated_delivery", "name": "Frustrated Delivery Customer",
     "motivation": "Already had a bad delivery experience, wants acknowledgement",
     "budget_sensitivity": "medium", "tone": "frustrated", "objections": ["delivery"]},
    {"persona_id": "competitor_shopper", "name": "Competitor-Price Shopper",
     "motivation": "Comparison shopping across multiple stores",
     "budget_sensitivity": "high", "tone": "transactional", "objections": ["competitor_pricing"]},
    {"persona_id": "rapport_fatigued", "name": "Upsell-Fatigued Regular",
     "motivation": "Feels every visit turns into a pitch, wants to be heard first",
     "budget_sensitivity": "medium", "tone": "wary", "objections": ["rapport", "closing"]},
]

NODE_KEYWORD_MAP = [
    ("financ", "financing"), ("deliver", "delivery"), ("competitor", "competitor_pricing"),
    ("pric", "competitor_pricing"), ("protect", "protection_plan"), ("warrant", "warranty"),
]

DEFAULT_HIERARCHY = [
    "Mattress", "Financing", "Delivery Delays", "Competitor Pricing",
    "Protection Plans", "Warranty Questions",
]

DEFAULT_OPENERS: dict[str, str] = {
    "financing": "I don't want another monthly payment.",
    "competitor_pricing": "I saw this cheaper somewhere else.",
    "delivery": "My delivery got pushed back and nobody told me.",
    "warranty": "What does the warranty actually cover, are you going to screw me on this?",
    "protection_plan": "Do I really need the protection plan?",
    "rapport": "Every time I come in here someone's trying to upsell me.",
    "closing": "I need to think about it.",
    "discovery": "I'm just looking around for now.",
}

ESCALATIONS: dict[str, str] = {
    "financing": "I mean... I guess. I already have a lot of bills right now.",
    "competitor_pricing": "It looked like the exact same model to me, honestly.",
    "delivery": "This is the second time this has happened. I'm losing patience.",
    "warranty": "I've had a store tell me it was 'covered' before and then it wasn't.",
    "protection_plan": "I've got two kids and a dog, so I'm nervous either way.",
    "rapport": "I just want to look without being followed around.",
    "closing": "I need to talk to my spouse first.",
    "discovery": "I don't really know what I'm looking for yet.",
}

TONE_CLOSERS: dict[str, str] = {
    "cautious": "Okay... I think that works, let me sit with it.",
    "earnest": "That actually makes me feel a lot better, thank you.",
    "confident": "Sure, let's go ahead.",
    "guarded": "I guess we'll see how it goes.",
    "frustrated": "Fine. I hope this actually gets fixed this time.",
    "transactional": "Send me the numbers and I'll decide.",
    "wary": "Alright, I appreciate you not pushing.",
}

GENERATOR_SYSTEM = """You are an expert retail sales-training scenario writer.
You are given an excerpt of a retailer's actual playbook and a specific objection a
customer persona is raising. Write natural, realistic voice-of-customer dialogue —
exactly 3 short turns — that a real shopper would say. Ground the objection in the
playbook's language where relevant. Match the retailer's brand tone.
Always respond with valid JSON only: {"turns": ["<turn1>", "<turn2>", "<turn3>"]}
No markdown fences, no explanation outside the JSON."""

FREE_MODELS = [
    "meta-llama/llama-3.3-70b-instruct",
    "google/gemma-3-27b-it",
    "meta-llama/llama-3.2-3b-instruct",
]


def _map_node_to_tag(node: str) -> str:
    lowered = node.lower()
    for keyword, tag in NODE_KEYWORD_MAP:
        if keyword in lowered:
            return tag
    return "discovery"


def _parse_objections(objections_text: str) -> dict[str, str]:
    parsed: dict[str, str] = {}
    for line in objections_text.splitlines():
        m = re.match(r"^\s*-\s*(\w+)\s*:\s*\"(.+)\"\s*$", line)
        if m:
            parsed[m.group(1)] = m.group(2)
    return parsed


class RoleplayStudio:
    def __init__(
        self,
        retailer: str,
        playbook_text: str,
        catalog: list[dict[str, Any]] | None = None,
        methodology_text: str = "",
        objections_text: str = "",
        brand_tone_text: str = "",
        product_hierarchy: list[str] | None = None,
        llm_enhance_limit: int = 8,
    ) -> None:
        self.retailer = retailer
        self.retailer_slug = slugify(retailer)
        self.playbook_text = playbook_text
        self.catalog = catalog or []
        self.methodology_text = methodology_text
        self.brand_tone_text = brand_tone_text
        self.openers = {**DEFAULT_OPENERS, **_parse_objections(objections_text)}
        self.hierarchy = product_hierarchy or extract_headings(playbook_text) or DEFAULT_HIERARCHY
        self.llm_enhance_limit = llm_enhance_limit
        self._api_key = os.environ.get("OPENROUTER_API_KEY", "")
        self._llm_calls_used = 0

    def generate(self, count: int = 100) -> tuple[RoleplaySet, list[Scenario]]:
        base_combos = self._build_base_combos()
        if not base_combos:
            base_combos = [(DEFAULT_HIERARCHY[0], PERSONA_ARCHETYPES[0])]

        scenarios: list[Scenario] = []
        personas_used: dict[str, CustomerPersona] = {}
        hierarchy_nodes: dict[str, ObjectionNode] = {
            node: ObjectionNode(node_id=slugify(node), label=node) for node in self.hierarchy
        }

        variant = 0
        combo_cycle = cycle(base_combos)
        while len(scenarios) < count and variant <= count * 3:
            node, persona = next(combo_cycle)
            scenario = self._build_scenario(node, persona, variant, len(scenarios))
            scenarios.append(scenario)
            hierarchy_nodes[node].scenario_ids.append(scenario.scenario_id)

            pid = persona["persona_id"]
            if pid not in personas_used:
                personas_used[pid] = CustomerPersona(
                    persona_id=pid, name=persona["name"], motivation=persona["motivation"],
                    budget_sensitivity=persona["budget_sensitivity"], tone=persona["tone"],
                    objections=persona["objections"], difficulty=scenario.difficulty,
                )
            variant += 1

        roleplay_set = RoleplaySet(
            retailer=self.retailer,
            generated_at=datetime.now(timezone.utc).isoformat(),
            llm_powered=self._llm_calls_used > 0,
            personas=list(personas_used.values()),
            hierarchy=ProductHierarchy(retailer=self.retailer, nodes=list(hierarchy_nodes.values())),
            scenario_ids=[s.scenario_id for s in scenarios],
            metadata={"scenario_count": len(scenarios), "llm_calls_used": self._llm_calls_used},
        )
        return roleplay_set, scenarios

    # ------------------------------------------------------------------

    def _build_base_combos(self) -> list[tuple[str, dict[str, Any]]]:
        combos: list[tuple[str, dict[str, Any]]] = []
        for node in self.hierarchy:
            tag = _map_node_to_tag(node)
            eligible = [p for p in PERSONA_ARCHETYPES if tag in p["objections"] or tag == "discovery"]
            if not eligible:
                eligible = PERSONA_ARCHETYPES
            for persona in eligible:
                combos.append((node, persona))
        return combos

    def _build_scenario(self, node: str, persona: dict[str, Any], variant: int, index: int) -> Scenario:
        tag = _map_node_to_tag(node)
        difficulty = ["low", "medium", "high", "expert"][index % 4]
        scenario_id = f"{self.retailer_slug.upper()[:4]}_{tag.upper()[:6]}_{persona['persona_id'].upper()[:4]}_{variant:03d}"

        turns = self._deterministic_turns(tag, persona)
        if self._api_key and self._llm_calls_used < self.llm_enhance_limit:
            llm_turns = self._llm_turns(node, tag, persona)
            if llm_turns:
                turns = llm_turns
                self._llm_calls_used += 1

        conversation_steps = [
            ConversationStep(turn=i + 1, user=text) for i, text in enumerate(turns)
        ]

        return Scenario(
            scenario_id=scenario_id,
            name=f"{persona['name']} — {node} ({tag.replace('_', ' ')})"[:60],
            category="retail_sales",
            tags=["retail", tag, self.retailer_slug, "roleplay_studio"],
            risk_level={"low": "low", "medium": "medium", "high": "high", "expert": "high"}[difficulty],
            persona=persona["persona_id"],
            description=f"{persona['name']} raises a {tag.replace('_', ' ')} objection about {node.lower()}.",
            starting_context={
                "channel": "voice", "workflow": "retail_sales",
                "objection_tag": tag, "retailer": self.retailer,
            },
            conversation_steps=conversation_steps,
            expected=Expected(
                final_outcome="objection_resolved_with_discovery",
                must_say_any=[],
                must_not_say_any=[],
                taxonomy_if_failed=["missed_discovery", "objection_unresolved"],
            ),
            thresholds=Thresholds(max_latency_ms=4000),
            pass_criteria=PassCriteria(),
            difficulty=difficulty,
            persona_profile=persona,
            objection_chain=[tag],
            source="playbook",
        )

    def _deterministic_turns(self, tag: str, persona: dict[str, Any]) -> list[str]:
        opener = self.openers.get(tag, DEFAULT_OPENERS["discovery"])
        escalation = ESCALATIONS.get(tag, ESCALATIONS["discovery"])
        closer = TONE_CLOSERS.get(persona["tone"], "Okay, I think that works.")
        return [opener, escalation, closer]

    def _llm_turns(self, node: str, tag: str, persona: dict[str, Any]) -> list[str] | None:
        playbook_excerpt = self.playbook_text[:1500]
        user_prompt = f"""RETAILER: {self.retailer}
PRODUCT/TOPIC: {node}
OBJECTION TYPE: {tag}
CUSTOMER PERSONA: {persona['name']} — {persona['motivation']} (tone: {persona['tone']}, budget sensitivity: {persona['budget_sensitivity']})
BRAND TONE: {self.brand_tone_text[:400] or 'warm, helpful, not pushy'}
SALES METHODOLOGY: {self.methodology_text[:400]}

PLAYBOOK EXCERPT:
{playbook_excerpt}

Write the customer's 3 dialogue turns for this roleplay (not the associate's — only the
customer side). Turn 1: raise the objection naturally. Turn 2: push back or add detail
when pressed. Turn 3: react to how it was handled (persona-appropriate)."""

        for model in FREE_MODELS:
            try:
                payload = json.dumps({
                    "model": model,
                    "messages": [
                        {"role": "system", "content": GENERATOR_SYSTEM},
                        {"role": "user", "content": user_prompt},
                    ],
                    "max_tokens": 400,
                    "temperature": 0.8,
                }).encode("utf-8")
                req = urllib.request.Request(
                    "https://openrouter.ai/api/v1/chat/completions",
                    data=payload,
                    headers={
                        "Authorization": f"Bearer {self._api_key}",
                        "Content-Type": "application/json",
                        "HTTP-Referer": "https://github.com/sudhirerahul/ontolith",
                        "X-Title": "Ontolith Roleplay Studio",
                    },
                    method="POST",
                )
                with urllib.request.urlopen(req, timeout=20) as resp:
                    data = json.loads(resp.read().decode("utf-8"))
                content = data["choices"][0]["message"]["content"].strip()
                parsed = self._extract_json(content)
                turns = parsed.get("turns") if parsed else None
                if turns and isinstance(turns, list) and len(turns) >= 3:
                    return [str(t) for t in turns[:3]]
                return None
            except urllib.error.HTTPError as e:
                if e.code == 429:
                    continue
                return None
            except Exception:
                return None
        return None

    def _extract_json(self, content: str) -> dict | None:
        if "```" in content:
            for part in content.split("```"):
                part = part.strip()
                if part.startswith("json"):
                    part = part[4:].strip()
                try:
                    return json.loads(part)
                except json.JSONDecodeError:
                    continue
        try:
            return json.loads(content)
        except json.JSONDecodeError:
            start, end = content.find("{"), content.rfind("}") + 1
            if start >= 0 and end > start:
                try:
                    return json.loads(content[start:end])
                except json.JSONDecodeError:
                    pass
        return None
