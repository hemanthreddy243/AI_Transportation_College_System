"""AI transport analyst: reviews the solver's plan and explains it to the admin.

The solver makes the decisions (seat limits are exact). Claude reads the plan and writes
a short briefing: what changed, fuel impact, risks (near-full buses, long rides,
students left without a seat) and concrete suggestions.

If no Anthropic credentials are configured, a plain rule-based summary is returned instead.
"""
from __future__ import annotations

import json
import logging

import anthropic

from . import config

log = logging.getLogger(__name__)

SYSTEM_PROMPT = """You are the transport operations analyst for an engineering college's bus service.
Each evening students vote whether they will take the bus the next morning. A routing solver then
combines stops into as few buses as possible without exceeding any bus's seat capacity.

You will receive the solver's plan as JSON. Write a briefing for the transport admin who must approve it:
1. One-paragraph summary: riders, buses used out of fleet, total km, estimated diesel, and the saving
   versus running the whole fleet.
2. A short line per bus: which stops it combines and how full it is.
3. Risks: buses above 90% full (no room for students who forgot to vote), routes over 50 km,
   any students left without a seat, stops with very low turnout.
4. At most three concrete, practical suggestions.

Use only numbers present in the JSON; do not invent data. Keep it under 300 words, plain markdown."""


def _rule_based_summary(plan: dict) -> str:
    lines = [
        f"**{plan['riders']} riders** on **{plan['buses_used']} of {plan['fleet_size']} buses**, "
        f"{plan['total_km']} km total by road, ~{plan['est_diesel_litres']} L diesel "
        f"(saves ~{plan['est_saving_litres']} L vs. running the whole fleet).",
        "",
    ]
    for r in plan["routes"]:
        stops = " → ".join(f"{s['name']} ({s['pickup']})" for s in r["stops"])
        pct = round(100 * r["load"] / r["capacity"])
        flag = "  ⚠ nearly full" if pct > 90 else ""
        mins = f" · ~{round(r['minutes'])} min" if r.get("minutes") else ""
        lines.append(f"- **Bus {r['bus_number']}**: {stops} → Campus · {r['load']}/{r['capacity']} ({pct}%) · {r['km']} km{mins}{flag}")
    if plan["unserved"]:
        lines += ["", "**⚠ Students without a seat:** " + ", ".join(f"{k}: {v}" for k, v in plan["unserved"].items())]
    lines += ["", "_AI briefing unavailable (no Anthropic credentials configured); showing rule-based summary._"]
    return "\n".join(lines)


def explain_plan(plan: dict) -> str:
    if not config.AI_ENABLED:
        return _rule_based_summary(plan)
    try:
        client = anthropic.Anthropic()
        response = client.beta.messages.create(
            model=config.CLAUDE_MODEL,
            max_tokens=4000,
            output_config={"effort": "low"},
            betas=["server-side-fallback-2026-07-01"],
            fallbacks="default",
            system=SYSTEM_PROMPT,
            messages=[{"role": "user", "content": "Plan JSON:\n" + json.dumps(plan, indent=2)}],
        )
    except anthropic.CredentialsError:
        log.info("No Anthropic credentials; using rule-based summary")
        return _rule_based_summary(plan)
    except TypeError as e:
        # The SDK raises TypeError when no API key / auth token / profile is configured at all.
        if "authentication method" not in str(e):
            raise
        log.info("No Anthropic credentials configured; using rule-based summary")
        return _rule_based_summary(plan)
    except anthropic.AuthenticationError:
        log.warning("Anthropic API key rejected; using rule-based summary")
        return _rule_based_summary(plan)
    except anthropic.RateLimitError:
        log.warning("Anthropic rate limit hit; using rule-based summary")
        return _rule_based_summary(plan)
    except anthropic.APIStatusError as e:
        log.warning("Anthropic API error %s; using rule-based summary", e.status_code)
        return _rule_based_summary(plan)
    except anthropic.APIConnectionError:
        log.warning("Could not reach Anthropic API; using rule-based summary")
        return _rule_based_summary(plan)

    if response.stop_reason == "refusal":
        return _rule_based_summary(plan)
    text = "".join(b.text for b in response.content if b.type == "text").strip()
    return text or _rule_based_summary(plan)
