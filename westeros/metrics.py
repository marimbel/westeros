"""Interaction metrics computed from an event log + snapshots."""
from collections import Counter, defaultdict


def gini(values):
    v = sorted(max(0.0, x) for x in values)
    n, s = len(v), sum(v)
    if n == 0 or s == 0:
        return 0.0
    cum = sum((i + 1) * x for i, x in enumerate(v))
    return round((2 * cum) / (n * s) - (n + 1) / n, 3)


def summarize(events, snapshots, winner=None, reason=None):
    c = Counter(e["type"] for e in events)
    battles = [e for e in events if e["type"] == "battle"]
    broken = [e for e in events if e["type"] == "alliance_broken"]
    proposals = Counter(e["kind"] for e in events if e["type"] == "proposal")
    accepted = Counter(e["kind"] for e in events if e["type"] == "accepted")
    war_pairs = Counter(tuple(sorted((e["attacker"], e["defender"]))) for e in battles if e["defender"] != "neutral")
    aggressor = Counter(e["attacker"] for e in battles)
    conquests = Counter(e["attacker"] for e in battles if e["conquered"])
    last = snapshots[-1]["factions"]
    per_faction = {}
    for f, s in last.items():
        per_faction[f] = dict(
            alive=s["alive"], power=s["power"], regions=s["regions"], troops=s["troops"], gold=s["gold"],
            battles_started=aggressor.get(f, 0), conquests=conquests.get(f, 0),
            betrayals=sum(1 for e in events if e["type"] in ("betrayal", "red_wedding") and e["by"] == f),
            alliances=sum(1 for e in events if e["type"] == "alliance_formed" and f in (e["a"], e["b"])),
            trades=sum(1 for e in events if e["type"] == "trade" and f in (e["a"], e["b"])),
            raids=sum(1 for e in events if e["type"] == "raid" and e["by"] == f),
            loans=sum(1 for e in events if e["type"] == "loan" and e["borrower"] == f),
            defaults=sum(1 for e in events if e["type"] == "default" and e["borrower"] == f),
        )
    # cooperation index: share of social interactions that were cooperative
    coop = c["alliance_formed"] + c["trade"] + c["loan"] + c["sellswords_hired"] + c["funding"]
    conflict = c["battle"] + c["raid"] + c["betrayal"] + c["red_wedding"] + c["alliance_broken"]
    throne = []
    prev = None
    for s in snapshots:
        h = s["owner"]["crownlands"]
        if h != prev:
            throne.append(dict(turn=s["turn"], holder=h)); prev = h
    return dict(
        winner=winner, reason=reason, turns=snapshots[-1]["turn"],
        counts=dict(c), proposals_by_kind=dict(proposals), accepted_by_kind=dict(accepted),
        acceptance_rate={k: round(accepted.get(k, 0) / v, 2) for k, v in proposals.items()},
        battles=len(battles), betrayals=c["betrayal"] + c["red_wedding"], red_weddings=c["red_wedding"],
        alliances_broken=len(broken),
        mean_alliance_duration=round(sum(e["duration"] for e in broken) / len(broken), 1) if broken else None,
        cooperation_index=round(coop / max(1, coop + conflict), 3),
        bloodiest_rivalries=[dict(pair=list(p), battles=n) for p, n in war_pairs.most_common(5)],
        power_gini_start=gini([s["power"] for s in snapshots[0]["factions"].values()]),
        power_gini_end=gini([s["power"] for s in last.values()]),
        survivors=[f for f, s in last.items() if s["alive"]],
        throne_history=throne,
        factions=per_faction,
    )


def timeseries(snapshots, key="power"):
    out = defaultdict(list)
    for s in snapshots:
        for f, v in s["factions"].items():
            out[f].append(v[key])
    return dict(out)
