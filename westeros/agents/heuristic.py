"""Rule-based agents whose behaviour is driven by personality traits
(aggression, honor, greed, loyalty). They are the baseline population; swap any
faction for an RL or LLM agent to study how it fares among them."""
import random

from ..world import FACTIONS, REGIONS, adjacency
from ..engine import SHIPS_PER_TROOPS, RECRUIT_COST, FOOD_PER_TROOP

ADJ = adjacency()


class BaseAgent:
    def __init__(self, fid, seed=0, traits=None):
        self.fid = fid
        self.rng = random.Random(f"{seed}-{fid}")
        self.traits = dict(FACTIONS[fid]["traits"], **(traits or {}))

    def act(self, obs):
        raise NotImplementedError


class RandomAgent(BaseAgent):
    """Picks legal-looking actions uniformly. Useful as a null model."""

    def act(self, obs):
        acts = [dict(type=self.rng.choice(["accept", "reject"]), proposal_id=p["id"]) for p in obs["proposals"]]
        for r in obs["my_regions"]:
            if self.rng.random() < 0.5:
                acts.append(dict(type="recruit", region=r, n=self.rng.randint(0, 300)))
        for r, info in obs["regions"].items():
            n = info["garrison"].get(self.fid, 0)
            if n > 100 and self.rng.random() < 0.3:
                acts.append(dict(type="move", src=r, dst=self.rng.choice(list(ADJ[r])), n=n // 2))
        others = [f for f, i in obs["factions"].items() if i["alive"] and f != self.fid]
        if others and self.rng.random() < 0.2:
            acts.append(dict(type=self.rng.choice(["propose_alliance", "break_alliance"]), to=self.rng.choice(others)))
        return acts


class HeuristicAgent(BaseAgent):
    def act(self, obs):
        T = self.traits
        acts = []
        acts += self._answer(obs)
        k = obs["factions"][self.fid]["kind"]
        if k == "bank":
            return acts + self._bank(obs)
        if k == "sellsword":
            return acts + self._sellsword(obs)
        acts += self._economy(obs)
        acts += self._recruit(obs)
        acts += self._diplomacy(obs)
        acts += self._military(obs)
        return acts[:8]

    # ----------------------------------------------------------- proposals
    def _answer(self, obs):
        T, out = self.traits, []
        F = obs["factions"]
        for p in obs["proposals"]:
            a, kind = p["from"], p["kind"]
            rel = F[a]["relation"]
            ok = False
            if kind in ("propose_alliance", "propose_marriage"):
                bar = 30 - 40 * T["loyalty"] + (25 if kind == "propose_marriage" else 0)
                # shared dread of the dead lowers the bar in winter
                if obs["season"] == "winter" and F.get("white_walkers", {}).get("regions", 0) >= 2:
                    bar -= 30
                if self.fid == "nights_watch" and a == "free_folk" and obs["season"] == "winter":
                    bar = -100   # let them through the Wall
                ok = rel + F[a]["reputation"] / 5 > bar
            elif kind == "propose_trade":
                give, get = p.get("give", {}), p.get("get", {})
                value = lambda d: d.get("gold", 0) + d.get("food", 0) * 0.8
                ok = value(give) >= value(get) * (1.0 + 0.3 * T["greed"]) and rel > -50
                reserve = {"food": obs["troops"] * FOOD_PER_TROOP * 6, "gold": 50}
                ok = ok and all(obs[r] - reserve[r] >= float(v) for r, v in get.items())
            elif kind == "lend":
                ok = obs["gold"] < 60 and T["greed"] > 0.3
            out.append(dict(type="accept" if ok else "reject", proposal_id=p["id"]))
        return out

    # ------------------------------------------------------------- economy
    def _economy(self, obs):
        T, acts = self.traits, []
        F = obs["factions"]
        me_kind = F[self.fid]["kind"]
        upkeep = obs["troops"] * FOOD_PER_TROOP
        income = sum(obs["regions"][r]["food"] * 10 for r in obs["my_regions"])
        if obs["season"] == "winter":
            income *= 0.5
        runway = obs["food"] / max(1, upkeep - income) if upkeep > income else 99
        if runway < 6 and obs["gold"] > 40:
            # buy grain from whoever has most food and isn't hostile (Tyrells usually)
            sellers = [f for f, i in F.items() if i["alive"] and f != self.fid and i["kind"] in ("house", "sellsword")
                       and i["relation"] > -40 and i["food"] >= 200]
            if sellers:
                seller = max(sellers, key=lambda f: F[f]["food"] + self.rng.random() * 50)
                amt = min(obs["gold"] * 0.5, 150)
                acts.append(dict(type="propose_trade", to=seller, give=dict(gold=round(amt)),
                                 get=dict(food=round(amt * 0.9))))
        for l in obs["loans"]:
            if l["due"] - obs["turn"] <= 2 and obs["gold"] > 0:
                if T["honor"] > 0.4 or self.fid == "lannister":   # a Lannister always pays his debts
                    acts.append(dict(type="repay_loan", amount=l["owed"]))
        at_war = any(i["relation"] < -40 and i["alive"] and i["kind"] != "undead" for f, i in F.items() if f != self.fid)
        if (obs["gold"] < 50 and at_war and not obs["loans"] and self.fid not in obs["defaulters"]
                and self.rng.random() < 0.3 + 0.5 * T["greed"] and F["iron_bank"]["alive"]
                and me_kind in ("house", "horde")):
            acts.append(dict(type="request_loan", amount=150))
        # hire sellswords when rich and threatened
        if at_war and obs["gold"] > 250 and F.get("golden_company", {}).get("alive") and obs["my_regions"] \
                and not any(c["hirer"] == self.fid for c in obs["contracts"]) and self.rng.random() < 0.3:
            front = max(obs["my_regions"], key=lambda r: self._threat(obs, r))
            acts.append(dict(type="hire", n=1000, region=front, price=35, turns=6))
        return acts

    def _recruit(self, obs):
        T, acts = self.traits, []
        if obs["factions"][self.fid]["kind"] in ("undead",):
            return acts
        reserve = 40 + 60 * (1 - T["aggression"])
        budget = max(0.0, obs["gold"] - reserve) if obs["factions"][self.fid]["kind"] != "tribe" else obs["food"] * 0.4
        # don't recruit what you can't feed
        income = sum(obs["regions"][r]["food"] * 10 for r in obs["my_regions"])
        feedable = (income * (0.5 if obs["season"] == "winter" else 1) + obs["food"] / 8) / FOOD_PER_TROOP
        room = max(0, int(feedable - obs["troops"]))
        regions = sorted(obs["my_regions"], key=lambda r: -self._threat(obs, r))
        for r in regions:
            n = int(min(obs["regions"][r]["levy"], budget / (RECRUIT_COST * (1.5 if obs["factions"][self.fid]["kind"] == "tribe" else 1)), room))
            if n >= 20:
                acts.append(dict(type="recruit", region=r, n=n))
                budget -= n * RECRUIT_COST; room -= n
        return acts

    # ----------------------------------------------------------- diplomacy
    def _diplomacy(self, obs):
        T, acts, F = self.traits, [], obs["factions"]
        me = F[self.fid]
        if me["kind"] == "undead":
            return acts
        allies = [f for f, i in F.items() if i["allied"] and i["alive"]]
        leader = self._leader(obs)
        cands = [(i["relation"] + i["reputation"] / 4 + (20 if leader and F[leader]["relation"] < 0 and f != leader else 0)
                  - (40 if f == leader else 0), f) for f, i in F.items()
                 if f != self.fid and i["alive"] and not i["allied"] and i["kind"] not in ("undead", "bank", "sellsword")]
        cands.sort(reverse=True)
        if cands and len(allies) < 1 + int(3 * (1 - T["aggression"])) and self.rng.random() < 0.25:
            score, target = cands[0]
            if score > 10:
                kind = "propose_marriage" if (score > 55 and self.rng.random() < 0.3) else "propose_alliance"
                acts.append(dict(type=kind, to=target))
                acts.append(dict(type="raven", to=target,
                                 text=f"{FACTIONS[self.fid]['name']} offers friendship. {FACTIONS[self.fid]['motto']}."))
        # sour alliances are abandoned (a prelude to betrayal)
        for f in allies:
            if F[f]["relation"] < -20 + 30 * (1 - T["loyalty"]) and F[f]["kind"] != "undead":
                acts.append(dict(type="break_alliance", to=f))
        # Free Folk flee south when the dead come
        if self.fid == "free_folk" and obs["season"] == "winter" and not F["nights_watch"]["allied"] and F["nights_watch"]["alive"]:
            acts.append(dict(type="propose_alliance", to="nights_watch"))
            acts.append(dict(type="raven", to="nights_watch", text="The dead are coming. Open the gate."))
        if self.fid == "nights_watch" and obs["winter_forecast"]:
            acts.append(dict(type="raven", to="all", text="Winter is coming and the dead with it. Send men to the Wall."))
        return acts

    # ------------------------------------------------------------ military
    def _leader(self, obs):
        """Balance of power: a throne-holder who dwarfs the rest becomes everyone's target."""
        F = obs["factions"]
        if obs["turn"] < 10:   # the King's peace holds for a while
            return None
        score = {f: i["regions"] * 10 + i["troops"] / 100 for f, i in F.items()
                 if i["alive"] and i["kind"] in ("house", "horde")}
        if not score:
            return None
        top = max(score, key=score.get)
        rest = sorted(score.values())
        median = rest[len(rest) // 2]
        if top != self.fid and (obs["iron_throne"] == top or score[top] > 1.8 * median):
            return top
        return None

    def _threat(self, obs, r):
        t = 0
        for n in ADJ[r]:
            o = obs["regions"][n]["owner"]
            if o and o != self.fid and not obs["factions"][o]["allied"]:
                hostility = max(0, -obs["factions"][o]["relation"]) / 100 + 0.2
                t += sum(v for k, v in obs["regions"][n]["garrison"].items() if k == o) * hostility
        return t

    def _military(self, obs):
        T, acts, F, R = self.traits, [], obs["factions"], obs["regions"]
        me = F[self.fid]
        mult = {"baratheon": 1.2, "dothraki": 1.25, "white_walkers": 1.2}.get(self.fid, 1.0)
        if me["kind"] == "bank":
            return acts
        if self.fid == "white_walkers" and obs["season"] != "winter":
            return acts
        margin = 1.9 - 0.8 * T["aggression"]
        war_threshold = -60 + 70 * T["aggression"]   # casus belli: how sour relations must be before war
        leader = self._leader(obs)
        options = []
        for src, info in R.items():
            mine = info["garrison"].get(self.fid, 0)
            if mine < 150:
                continue
            keep = 0 if self.fid == "white_walkers" else int(mine * (0.15 + 0.35 * (1 - T["aggression"])))
            if self.fid == "nights_watch":
                keep = int(mine * 0.6)
            avail = mine - keep
            targets = list(ADJ[src].items())
            if info["owner"] not in (self.fid, None) and not F[info["owner"]]["allied"]:
                targets.append((src, "land"))  # hostile hosts around us
            for dst, edge in targets:
                o = R[dst]["owner"]
                if o == self.fid:
                    continue
                if edge == "sea" and self.fid != "greyjoy" and obs["ships"] * SHIPS_PER_TROOPS < avail * 0.5 \
                        and not any(F[a]["allied"] for a in ("greyjoy", "targaryen") if a in F):
                    continue
                if self.fid == "nights_watch" and o not in (None, "white_walkers", "free_folk"):
                    continue
                if dst == "lands_of_always_winter" and self.fid != "white_walkers":
                    continue
                eff_rel = (F[o]["relation"] - (50 if o == leader else 0)) if o else 0
                if o and not F[o]["allied"] and eff_rel > war_threshold and self.fid != "white_walkers":
                    continue
                betray = False
                if o and F[o]["allied"]:
                    # betrayal: only the faithless, only when the prize is large
                    if not (T["honor"] < 0.5 and self.rng.random() < (1 - T["honor"]) * T["greed"] * 0.5):
                        continue
                    betray = True
                d = sum(v for k, v in R[dst]["garrison"].items() if k == o or k == "neutral")
                d *= R[dst]["defense"] * (1.4 if (o == "martell" and dst == "dorne") else 1.0)
                if o == "targaryen":
                    d += F["targaryen"]["dragons"] * obs["dragon_power"]
                a = avail * mult + (obs["dragons"] * obs["dragon_power"] if self.fid == "targaryen" else 0)
                if a <= d * margin:
                    # raid instead if we are raiders and the target is rich
                    if self.fid in ("greyjoy", "free_folk", "dothraki") and o and not F[o]["allied"] and o != "white_walkers" \
                            and a > d * 0.5 and self.rng.random() < T["aggression"] * 0.5:
                        options.append((0.5 * (R[dst]["food"] + R[dst]["gold"]), "raid", src, dst, avail, False))
                    continue
                value = R[dst]["food"] + R[dst]["gold"] + (25 if R[dst]["throne"] else 0) + 3
                hate = (-F[o]["relation"] / 25) if o else 0
                if self.fid == "white_walkers":
                    value = 10 + REGIONS[dst]["y"] / 50   # the dead march south
                options.append((value + hate + self.rng.random(), "move", src, dst, avail, betray))
        options.sort(reverse=True)
        used = set()
        n_attacks = 1 + int(2 * T["aggression"])
        for score, kind, src, dst, n, betray in options:
            if src in used or n_attacks <= 0:
                continue
            if betray:
                acts.append(dict(type="break_alliance", to=R[dst]["owner"]))
            acts.append(dict(type=kind, src=src, dst=dst, n=n))
            used.add(src); n_attacks -= 1
        # the Great War: honourable houses send men north when the dead come
        ww = F.get("white_walkers", {})
        if obs["season"] == "winter" and ww.get("alive") and T["honor"] >= 0.5 and me["kind"] in ("house", "order"):
            front = [r for r, i in R.items() if i["owner"] in ("white_walkers",)]
            for src in obs["my_regions"]:
                if src in used: continue
                for dst in ADJ[src]:
                    o = R[dst]["owner"]
                    if o == "nights_watch" or (o and F[o]["allied"]) or o == self.fid:
                        if any(n in front for n in ADJ[dst]) or dst == "the_wall":
                            mine = R[src]["garrison"].get(self.fid, 0)
                            if mine > 500 and self.rng.random() < T["honor"] * 0.5:
                                acts.append(dict(type="move", src=src, dst=dst, n=int(mine * 0.4)))
                                used.add(src)
                            break
        # consolidate: push idle troops from safe interior regions toward the frontier
        for src in obs["my_regions"]:
            if src in used:
                continue
            mine = R[src]["garrison"].get(self.fid, 0)
            if self._threat(obs, src) == 0 and mine > 400:
                nbrs = [d for d in ADJ[src] if R[d]["owner"] == self.fid and ADJ[src][d] == "land"]
                if nbrs:
                    dst = max(nbrs, key=lambda d: self._threat(obs, d))
                    if self._threat(obs, dst) > 0:
                        acts.append(dict(type="move", src=src, dst=dst, n=int(mine * 0.6)))
        return acts

    # --------------------------------------------------------- iron bank
    def _bank(self, obs):
        acts, F = [], obs["factions"]
        # punish defaulters by funding their strongest enemy
        for d in obs["defaulters"]:
            if not F[d]["alive"]:
                continue
            enemies = [(i["troops"], f) for f, i in F.items()
                       if i["alive"] and f not in (d, "iron_bank") and i["kind"] == "house"
                       and obs["factions"][f]["relation"] >= 0 and self._rel_between_guess(obs, f, d) < 0]
            if enemies and obs["gold"] > 300 and self.rng.random() < 0.3:
                acts.append(dict(type="fund", to=max(enemies)[1], amount=150))
                acts.append(dict(type="raven", to=d, text="The Iron Bank will have its due."))
        # offer loans to solvent houses (the bank profits from war)
        if obs["gold"] > 900 and self.rng.random() < 0.15:
            houses = [f for f, i in F.items() if i["alive"] and i["kind"] == "house" and f not in obs["defaulters"]
                      and i["reputation"] >= 45]
            if houses:
                acts.append(dict(type="lend", to=self.rng.choice(houses), amount=200))
        return acts

    def _rel_between_guess(self, obs, a, b):
        # the bank sees public news: who fought whom recently
        hostile = any(e["type"] == "battle" and {e.get("attacker"), e.get("defender")} == {a, b} for e in obs["news"])
        return -50 if hostile else (-10 if a != b else 0)

    def _sellsword(self, obs):
        return []  # the Golden Company only answers contracts (see GoldenCompanyAgent._answer)


class IronBankAgent(HeuristicAgent):
    def _answer(self, obs):
        out = []
        for p in obs["proposals"]:
            ok = False
            if p["kind"] == "request_loan":
                b = obs["factions"][p["from"]]
                amt = float(p.get("amount", 0))
                ok = (p["from"] not in obs["defaulters"] and b["reputation"] >= 35 and b["kind"] in ("house", "horde", "sellsword") and amt <= 400
                      and obs["gold"] > amt * 1.5 and b["regions"] > 0)
            out.append(dict(type="accept" if ok else "reject", proposal_id=p["id"]))
        return out


class GoldenCompanyAgent(HeuristicAgent):
    def _answer(self, obs):
        out = []
        for p in obs["proposals"]:
            ok = False
            if p["kind"] == "hire":
                n = int(p.get("n", 0))
                fair = n / 100 * 3 * (0.7 + 0.6 * self.traits["greed"]) * 0.6
                ok = float(p.get("price", 0)) >= fair and obs["troops"] >= n * 0.5 and obs["factions"][p["from"]]["relation"] > -30
            elif p["kind"] == "propose_trade":
                ok = p.get("give", {}).get("gold", 0) >= p.get("get", {}).get("food", 0) * 1.2 and obs["food"] > 100
            out.append(dict(type="accept" if ok else "reject", proposal_id=p["id"]))
        return out


def default_agent(fid, seed=0):
    if fid == "iron_bank":
        return IronBankAgent(fid, seed)
    if fid == "golden_company":
        return GoldenCompanyAgent(fid, seed)
    return HeuristicAgent(fid, seed)
