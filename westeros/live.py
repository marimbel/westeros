"""Step-by-step session used by the live browser world (via Pyodide) and the site builder.

Each step returns a compact JSON-able frame: the state after the turn plus the events
that produced it, which the pixel map animates."""
import json

from .engine import WesterosEnv
from .agents.heuristic import default_agent

KEEP = {"move", "battle", "raid", "recruit", "alliance_formed", "alliance_broken", "betrayal", "red_wedding",
        "throne_seized", "eliminated", "season", "trade", "loan", "default", "sellswords_hired", "funding",
        "starvation", "dead_retreat", "game_over", "raven", "contract_ended", "loan_repaid"}


def frame(env, snap, done=False):
    return dict(
        turn=snap["turn"], season=snap["season"], owner=snap["owner"], garrison=snap["garrison"],
        factions={f: {k: s[k] for k in ("alive", "troops", "regions", "gold", "food", "dragons", "power")}
                  for f, s in snap["factions"].items()},
        allies=snap["allies"], married=snap["married"],
        events=[e for e in snap["events"] if e["type"] in KEEP],
        done=done, winner=env.winner if done else None, reason=env.win_reason if done else None,
    )


class LiveSession:
    def __init__(self, seed=0, max_turns=150):
        self.env = WesterosEnv(seed=seed, max_turns=max_turns)
        self.obs = self.env.reset()
        self.agents = {f: default_agent(f, seed) for f in self.env.faction_ids}
        self.done = False

    def first(self):
        return json.dumps(frame(self.env, self.env.snapshots[0]))

    def step(self):
        if self.done:
            return json.dumps(None)
        acts = {f: self.agents[f].act(o) for f, o in self.obs.items()}
        self.obs, _, self.done, _ = self.env.step(acts)
        return json.dumps(frame(self.env, self.env.snapshots[-1], self.done))


def record(seed=0, max_turns=150):
    s = LiveSession(seed, max_turns)
    frames = [json.loads(s.first())]
    while not s.done:
        frames.append(json.loads(s.step()))
    return frames
