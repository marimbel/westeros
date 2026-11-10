"""An LLM-driven faction (Claude via the Anthropic API).

The model plays the house in character: it gets its persona, the rules, a compact
observation and the action schema, and must reply with a JSON list of actions plus a
short private rationale (logged, so you can study *why* agents cooperate or betray).

    pip install anthropic && export ANTHROPIC_API_KEY=...
    python run.py --llm stark,lannister --turns 60
"""
import json
import os
import re

from ..engine import ACTION_SCHEMA, MAX_ACTIONS
from ..world import FACTIONS, adjacency
from .heuristic import default_agent

ADJ = adjacency()

SYSTEM = """You are the ruling mind of {name} in a simulated Westeros. Motto: "{motto}".
Your special ability: {special}
Personality (0-1): {traits}.

Goal: survive and grow strong. A great house wins by holding King's Landing (crownlands)
for 12 consecutive turns. If the White Walkers hold 6 regions, the Long Night falls and
everyone loses. Resources are scarce: troops eat food (1 per 60/turn), recruiting costs
gold (0.1/troop), winter cuts northern harvests by 65%. Proposals you send arrive next
turn; you answer proposals sent to you with accept/reject by proposal_id.
Moving troops into a hostile or neutral region attacks it. To attack an ally you must
break_alliance first (that is a betrayal, and everyone remembers).

Map (region: neighbours, ~ = sea crossing needing ships, 1 ship carries 500):
{map}

Actions (max {max_actions} per turn), each a JSON object:
{schema}

Reply with ONLY a JSON object: {{"thoughts": "<2 sentences, private>", "actions": [ ... ]}}"""


def _map_text():
    return "\n".join(f"- {r}: " + ", ".join(("~" if e == "sea" else "") + n for n, e in nbrs.items())
                     for r, nbrs in ADJ.items())


def compact(obs):
    """Shrink the observation so it fits comfortably in a prompt."""
    me = obs["me"]
    regions = {}
    for r, i in obs["regions"].items():
        if i["visible"] or i["owner"] == me:
            regions[r] = dict(owner=i["owner"], garrison=i["garrison"], food=i["food"], gold=i["gold"],
                              defense=i["defense"])
        else:
            regions[r] = dict(owner=i["owner"])
    return dict(
        turn=obs["turn"], season=obs["season"], winter_forecast=obs["winter_forecast"],
        gold=obs["gold"], food=obs["food"], troops=obs["troops"], ships=obs["ships"], dragons=obs["dragons"],
        my_regions=obs["my_regions"], loans=obs["loans"], iron_throne=obs["iron_throne"],
        factions={f: {k: v for k, v in i.items() if k != "kind"} for f, i in obs["factions"].items() if i["alive"]},
        regions=regions, proposals_to_you=obs["proposals"], ravens_to_you=obs["ravens"],
        news=[{k: v for k, v in e.items() if k not in ("turn",)} for e in obs["news"][-15:]],
    )


class LLMAgent:
    def __init__(self, fid, seed=0, model=None, max_tokens=900):
        self.fid = fid
        self.model = model or os.environ.get("WESTEROS_MODEL", "claude-haiku-5-5")
        self.max_tokens = max_tokens
        self.fallback = default_agent(fid, seed)
        self.thoughts = []  # (turn, text) — the agent's private reasoning
        d = FACTIONS[fid]
        self.system = SYSTEM.format(name=d["name"], motto=d["motto"], special=obs_special(fid),
                                    traits=json.dumps(d["traits"]), map=_map_text(), max_actions=MAX_ACTIONS,
                                    schema="\n".join(f"- {k}: {v}" for k, v in ACTION_SCHEMA.items()))
        try:
            import anthropic
            self.client = anthropic.Anthropic()
        except Exception as ex:  # no SDK / key: degrade gracefully
            print(f"[{fid}] LLM unavailable ({ex}); using heuristic fallback")
            self.client = None

    def act(self, obs):
        if self.client is None:
            return self.fallback.act(obs)
        try:
            msg = self.client.messages.create(
                model=self.model, max_tokens=self.max_tokens, system=self.system,
                messages=[{"role": "user", "content": "Current situation:\n" + json.dumps(compact(obs))}])
            text = "".join(b.text for b in msg.content if getattr(b, "type", "") == "text")
            data = json.loads(re.search(r"\{.*\}", text, re.S).group(0))
            self.thoughts.append(dict(turn=obs["turn"], faction=self.fid, thoughts=data.get("thoughts", "")))
            acts = [a for a in data.get("actions", []) if isinstance(a, dict) and "type" in a]
            return acts[:MAX_ACTIONS]
        except Exception as ex:
            self.thoughts.append(dict(turn=obs["turn"], faction=self.fid, thoughts=f"(error: {ex}; fallback)"))
            return self.fallback.act(obs)


def obs_special(fid):
    from ..world import SPECIALS
    return SPECIALS[fid]
