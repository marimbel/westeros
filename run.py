#!/usr/bin/env python3
"""Run Westeros simulations.

  python run.py                           # one chronicle, writes runs/seed0/ (+ replay.html)
  python run.py --seed 7 --turns 120
  python run.py --batch 50                # 50 seeds -> runs/batch/outcomes.csv + aggregate.json
  python run.py --llm stark,lannister     # those houses are played by Claude (needs ANTHROPIC_API_KEY)
  python run.py --random greyjoy          # null-model agent for a faction
  python run.py --traits stark:honor=0.1  # personality ablations
"""
import argparse
import csv
import json
import os
import statistics
from collections import Counter

from westeros.engine import WesterosEnv
from westeros.world import FACTIONS, REGIONS, adjacency, SPECIALS
from westeros.agents.heuristic import default_agent, RandomAgent, HeuristicAgent
from westeros.metrics import summarize

HERE = os.path.dirname(os.path.abspath(__file__))


def build_agents(seed, llm=(), rand=(), traits=None):
    agents = {}
    for f in FACTIONS:
        if f in llm:
            from westeros.agents.llm import LLMAgent
            agents[f] = LLMAgent(f, seed)
        elif f in rand:
            agents[f] = RandomAgent(f, seed)
        else:
            agents[f] = default_agent(f, seed)
            if traits and f in traits and isinstance(agents[f], HeuristicAgent):
                agents[f].traits.update(traits[f])
    return agents


def run_one(seed=0, turns=150, llm=(), rand=(), traits=None, verbose=False):
    env = WesterosEnv(seed=seed, max_turns=turns)
    obs = env.reset()
    agents = build_agents(seed, llm, rand, traits)
    done = False
    while not done:
        actions = {f: agents[f].act(o) for f, o in obs.items()}
        obs, rewards, done, info = env.step(actions)
        if verbose:
            for e in info["events"]:
                if e["type"] in ("battle", "betrayal", "red_wedding", "alliance_formed", "throne_seized",
                                 "eliminated", "season", "default", "game_over"):
                    print(f"t{e['turn']:>3} {e['type']:<16} " + ", ".join(f"{k}={v}" for k, v in e.items()
                                                                       if k not in ("turn", "type")))
    thoughts = [t for a in agents.values() for t in getattr(a, "thoughts", [])]
    return env, summarize(env.events, env.snapshots, env.winner, env.win_reason), thoughts


def parse_traits(spec):
    out = {}
    for item in spec or []:
        f, kv = item.split(":", 1)
        out.setdefault(f, {})
        for pair in kv.split(","):
            k, v = pair.split("=")
            out[f][k] = float(v)
    return out


def write_replay(env, summary, thoughts, path):
    world = dict(regions=REGIONS, adjacency=adjacency(),
                 factions={f: dict(name=d["name"], motto=d["motto"], color=d["color"], kind=d["kind"],
                                   special=SPECIALS[f]) for f, d in FACTIONS.items()})
    data = dict(world=world, snapshots=env.snapshots, summary=summary, thoughts=thoughts, seed=env.seed)
    with open(os.path.join(HERE, "viewer", "template.html")) as fh:
        html = fh.read()
    html = html.replace("/*__DATA__*/null", json.dumps(data, separators=(",", ":")))
    with open(path, "w") as fh:
        fh.write(html)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--seed", type=int, default=0)
    ap.add_argument("--turns", type=int, default=150)
    ap.add_argument("--batch", type=int, default=0)
    ap.add_argument("--llm", default="")
    ap.add_argument("--random", default="")
    ap.add_argument("--traits", nargs="*")
    ap.add_argument("--out", default="runs")
    ap.add_argument("-v", "--verbose", action="store_true")
    a = ap.parse_args()
    llm = [x for x in a.llm.split(",") if x]
    rand = [x for x in a.random.split(",") if x]
    traits = parse_traits(a.traits)

    if a.batch:
        out = os.path.join(a.out, "batch"); os.makedirs(out, exist_ok=True)
        rows, sums = [], []
        for s in range(a.batch):
            env, summ, _ = run_one(s, a.turns, llm, rand, traits)
            sums.append(summ)
            row = dict(seed=s, winner=summ["winner"], reason=summ["reason"], turns=summ["turns"],
                       battles=summ["battles"], betrayals=summ["betrayals"], red_weddings=summ["red_weddings"],
                       cooperation_index=summ["cooperation_index"], gini_end=summ["power_gini_end"],
                       survivors=len(summ["survivors"]))
            for f, fs in summ["factions"].items():
                row[f"{f}_alive"] = int(fs["alive"]); row[f"{f}_power"] = fs["power"]
            rows.append(row)
            print(f"seed {s:>3}: {summ['winner']:<15} t={summ['turns']:<4} battles={summ['battles']:<4} "
                  f"betrayals={summ['betrayals']:<3} coop={summ['cooperation_index']}")
        with open(os.path.join(out, "outcomes.csv"), "w", newline="") as fh:
            w = csv.DictWriter(fh, fieldnames=list(rows[0])); w.writeheader(); w.writerows(rows)
        agg = dict(
            runs=a.batch, win_counts=dict(Counter(r["winner"] for r in rows).most_common()),
            win_reasons=dict(Counter(r["reason"] for r in rows)),
            mean_battles=statistics.mean(r["battles"] for r in rows),
            mean_betrayals=statistics.mean(r["betrayals"] for r in rows),
            mean_cooperation_index=round(statistics.mean(r["cooperation_index"] for r in rows), 3),
            survival_rate={f: round(statistics.mean(r[f"{f}_alive"] for r in rows), 2) for f in FACTIONS},
            mean_final_power={f: round(statistics.mean(r[f"{f}_power"] for r in rows), 1) for f in FACTIONS},
        )
        with open(os.path.join(out, "aggregate.json"), "w") as fh:
            json.dump(agg, fh, indent=2)
        print(json.dumps(agg, indent=2))
        return

    out = os.path.join(a.out, f"seed{a.seed}"); os.makedirs(out, exist_ok=True)
    env, summ, thoughts = run_one(a.seed, a.turns, llm, rand, traits, a.verbose)
    with open(os.path.join(out, "events.jsonl"), "w") as fh:
        for e in env.events: fh.write(json.dumps(e) + "\n")
    with open(os.path.join(out, "snapshots.json"), "w") as fh:
        json.dump(env.snapshots, fh)
    with open(os.path.join(out, "summary.json"), "w") as fh:
        json.dump(summ, fh, indent=2)
    if thoughts:
        with open(os.path.join(out, "thoughts.jsonl"), "w") as fh:
            for t in thoughts: fh.write(json.dumps(t) + "\n")
    write_replay(env, summ, thoughts, os.path.join(out, "replay.html"))
    print(f"\nWinner: {summ['winner']} — {summ['reason']} (turn {summ['turns']})")
    print(f"battles={summ['battles']} betrayals={summ['betrayals']} coop_index={summ['cooperation_index']}")
    print(f"wrote {out}/ (open replay.html)")


if __name__ == "__main__":
    main()
