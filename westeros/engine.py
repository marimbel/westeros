"""WesterosEnv: a turn-based, multi-agent, resource-competition sandbox.

Gym/PettingZoo-flavoured API:
    env = WesterosEnv(seed=0)
    obs = env.reset()                         # {faction_id: observation}
    obs, rewards, done, info = env.step({fid: [action, ...]})

Each turn every living faction submits up to MAX_ACTIONS actions (dicts). Proposals made
this turn land in the recipient's observation next turn and must be answered with
accept/reject (unanswered proposals expire). See ACTION_SCHEMA for the full list.
"""
import math
import random
from collections import defaultdict

from .world import (REGIONS, FACTIONS, SPECIALS, ALLIED, MARRIED, LORE_RELATIONS,
                    INCOME_SCALE, adjacency)

MAX_ACTIONS = 8
FOOD_PER_TROOP = 1 / 60      # food eaten per soldier per turn
RECRUIT_COST = 0.1           # gold per soldier
THRONE_TURNS = 30            # consecutive turns holding King's Landing to win
LONG_NIGHT_REGIONS = 7       # White Walkers win if they hold this many regions
THRONE_MIN_REGIONS = 6       # ...while ruling at least this many regions
SHIPS_PER_TROOPS = 100       # 1 ship carries 100 soldiers
LOAN_INTEREST = 0.25
LOAN_TERM = 10

ACTION_SCHEMA = {
    "recruit":         "{type, region, n}  raise n troops in an owned region (cost 0.1 gold each; free folk pay food)",
    "move":            "{type, src, dst, n}  move troops; into a hostile/neutral region = ATTACK. Sea edges need ships (yours + allies')",
    "raid":            "{type, src, dst, n}  greyjoy/free_folk/dothraki: hit an adjacent region, steal food+gold, then return",
    "propose_alliance":"{type, to}",
    "propose_marriage":"{type, to}  stronger alliance; breaking it is a grave betrayal",
    "break_alliance":  "{type, to}",
    "propose_trade":   "{type, to, give:{gold,food}, get:{gold,food}}",
    "request_loan":    "{type, amount}  to the Iron Bank; repay amount*(1+0.25) within 10 turns or default",
    "repay_loan":      "{type, amount}",
    "hire":            "{type, n, region, price, turns}  hire Golden Company troops into an owned region for price gold/turn",
    "lend":            "{type, to, amount}  iron_bank only: unsolicited loan offer (recipient must accept)",
    "fund":            "{type, to, amount}  gift gold to another faction (the Iron Bank uses this to punish defaulters)",
    "accept":          "{type, proposal_id}",
    "reject":          "{type, proposal_id}",
    "raven":           "{type, to, text}  free-text message delivered next turn (to may be 'all')",
}


def _pair(a, b):
    return tuple(sorted((a, b)))


class WesterosEnv:
    def __init__(self, seed=0, max_turns=150, factions=None, fog_of_war=True):
        self.seed = seed
        self.max_turns = max_turns
        self.faction_ids = list(factions or FACTIONS.keys())
        self.fog_of_war = fog_of_war
        self.adj = adjacency()

    # ------------------------------------------------------------------ setup
    def reset(self):
        self.rng = random.Random(self.seed)
        self.turn = 0
        self.owner = {r: None for r in REGIONS}
        self.garrison = {r: defaultdict(int) for r in REGIONS}
        self.garrison["dragonstone"]["neutral"] = 300
        self.f = {}
        for fid in self.faction_ids:
            d = FACTIONS[fid]
            self.f[fid] = dict(gold=float(d["gold"]), food=float(d["food"]), ships=d["ships"],
                               dragons=d["dragons"], alive=True, reputation=50 + 30 * d["traits"]["honor"],
                               eliminated_turn=None, throne_turns=0)
            per = d["troops"] // len(d["regions"])
            for r in d["regions"]:
                self.owner[r] = fid
                self.garrison[r][fid] += per
        self.rel = {}
        for a in self.faction_ids:
            for b in self.faction_ids:
                if a < b:
                    self.rel[(a, b)] = LORE_RELATIONS.get((a, b), LORE_RELATIONS.get((b, a), 0))
        self.allies = {_pair(a, b) for a, b in ALLIED if a in self.f and b in self.f}
        self.married = {_pair(a, b) for a, b in MARRIED if a in self.f and b in self.f}
        self.alliance_start = {p: 0 for p in self.allies}
        self.loans = []           # {borrower, owed, due}
        self.contracts = []       # golden company: {hirer, n, price, until, region}
        self.blacklist = set()
        self.proposals = {}       # id -> proposal (pending, delivered next turn)
        self._pid = 0
        self.ravens = defaultdict(list)
        self.events = []          # full log
        self.last_events = []
        self.season = "summer"
        self.season_left = self.rng.randint(15, 30)
        self.winner = None
        self.win_reason = None
        self._vs_dead = False
        self.snapshots = [self.snapshot()]
        return {fid: self.observe(fid) for fid in self.alive()}

    # ---------------------------------------------------------------- helpers
    def alive(self):
        return [f for f in self.faction_ids if self.f[f]["alive"]]

    def relation(self, a, b):
        return 0 if a == b else self.rel[_pair(a, b)]

    def shift_rel(self, a, b, d):
        if a == b or a not in self.f or b not in self.f:
            return
        p = _pair(a, b)
        self.rel[p] = max(-100, min(100, self.rel[p] + d))

    def allied(self, a, b):
        return _pair(a, b) in self.allies

    def troops(self, fid):
        return sum(g.get(fid, 0) for g in self.garrison.values())

    def regions_of(self, fid):
        return [r for r, o in self.owner.items() if o == fid]

    def kind(self, fid):
        return FACTIONS[fid]["kind"]

    def log(self, etype, **kw):
        e = dict(turn=self.turn, type=etype, **kw)
        self.events.append(e)
        self._turn_events.append(e)
        return e

    def power(self, fid):
        s = self.f[fid]
        return (len(self.regions_of(fid)) * 10 + self.troops(fid) / 100 + s["gold"] / 20 + s["food"] / 50
                + s["dragons"] * 8 + (25 if self.owner["crownlands"] == fid else 0))

    def dragon_power(self):
        """Dragons start young and grow: 100 strength each at turn 0, up to 500 by turn 80."""
        return 100 + min(400, self.turn * 5)

    def ships_available(self, fid):
        return self.f[fid]["ships"] + sum(self.f[o]["ships"] for o in self.alive() if o != fid and self.allied(fid, o))

    # ------------------------------------------------------------ observation
    def observe(self, fid):
        me = self.f[fid]
        mine = set(self.regions_of(fid))
        visible = set(mine)
        for r in mine:
            visible |= set(self.adj[r])
        for r, g in self.garrison.items():
            if g.get(fid, 0) > 0:
                visible.add(r); visible |= set(self.adj[r])
        regions = {}
        for r, info in REGIONS.items():
            g = {k: v for k, v in self.garrison[r].items() if v > 0}
            if self.fog_of_war and r not in visible:
                g = {k: int(round(v, -3)) for k, v in g.items()}  # rumours only: rounded to 1000s
            regions[r] = dict(owner=self.owner[r], garrison=g, visible=r in visible or not self.fog_of_war,
                              food=info["food"], gold=info["gold"], levy=info["levy"], defense=info["defense"],
                              throne=info.get("throne", False))
        factions = {}
        for o in self.faction_ids:
            t = self.troops(o)
            factions[o] = dict(alive=self.f[o]["alive"], kind=self.kind(o), regions=len(self.regions_of(o)),
                               troops=t if (o == fid or not self.fog_of_war) else int(round(t, -3)),
                               food=round(self.f[o]["food"], -2 if (self.fog_of_war and o != fid) else 0),
                               gold=round(self.f[o]["gold"], -2 if (self.fog_of_war and o != fid) else 0),
                               reputation=round(self.f[o]["reputation"]), dragons=self.f[o]["dragons"],
                               relation=self.relation(fid, o), allied=self.allied(fid, o),
                               married=_pair(fid, o) in self.married)
        props = [p for p in self.proposals.values() if p["to"] == fid]
        return dict(
            turn=self.turn, season=self.season,
            winter_forecast=(self.season == "summer" and self.season_left <= 6),
            me=fid, name=FACTIONS[fid]["name"], motto=FACTIONS[fid]["motto"], special=SPECIALS[fid],
            gold=round(me["gold"], 1), food=round(me["food"], 1), ships=me["ships"], dragons=me["dragons"],
            dragon_power=self.dragon_power(),
            troops=self.troops(fid), my_regions=sorted(mine), reputation=round(me["reputation"]),
            loans=[dict(owed=round(l["owed"], 1), due=l["due"]) for l in self.loans if l["borrower"] == fid],
            contracts=[dict(c) for c in self.contracts if fid in (c["hirer"], "golden_company")],
            iron_throne=self.owner["crownlands"], throne_turns=me["throne_turns"],
            regions=regions, factions=factions, proposals=props,
            ravens=list(self.ravens.get(fid, [])),
            defaulters=sorted(self.blacklist),
            news=[e for e in self.last_events if e["type"] not in ("raven",)][-40:],
        )

    # ------------------------------------------------------------------- step
    def step(self, actions):
        self._turn_events = []
        self._broken_this_turn, self._broken_married = set(), set()
        self._dragons_used = False
        before ={f: self.power(f) for f in self.alive()}
        actions = {f: list(a or [])[:MAX_ACTIONS] for f, a in actions.items() if f in self.f and self.f[f]["alive"]}
        delivered = self.proposals
        self.proposals = {}
        self.ravens = defaultdict(list)

        # 1. answers to last turn's proposals
        for fid, acts in actions.items():
            for a in acts:
                if a.get("type") in ("accept", "reject"):
                    p = delivered.get(a.get("proposal_id"))
                    if p and p["to"] == fid:
                        self._resolve(p, a["type"] == "accept")
                        p["answered"] = True
        for p in delivered.values():
            if not p.get("answered"):
                self.log("proposal_expired", by=p["from"], to=p["to"], kind=p["kind"])

        # 2. internal + diplomatic actions
        moves = []
        for fid, acts in actions.items():
            for a in acts:
                t = a.get("type")
                try:
                    if t == "recruit": self._recruit(fid, a)
                    elif t in ("move", "raid"): moves.append((fid, a))
                    elif t in ("propose_alliance", "propose_marriage", "propose_trade", "hire", "lend"):
                        self._propose(fid, a)
                    elif t == "request_loan": self._propose(fid, dict(a, to="iron_bank"))
                    elif t == "break_alliance": self._break(fid, a.get("to"))
                    elif t == "repay_loan": self._repay(fid, float(a.get("amount", 0)))
                    elif t == "fund": self._fund(fid, a)
                    elif t == "raven": self._raven(fid, a)
                except (KeyError, TypeError, ValueError) as ex:
                    self.log("invalid_action", by=fid, action=a, error=str(ex))

        # 3. military: peaceful moves first, then attacks/raids in random order
        self.rng.shuffle(moves)
        moves.sort(key=lambda m: 0 if self._is_peaceful(m[0], m[1]) else 1)
        for fid, a in moves:
            try:
                self._move(fid, a)
            except (KeyError, TypeError, ValueError) as ex:
                self.log("invalid_action", by=fid, action=a, error=str(ex))

        # 4. economy, debts, contracts, the supernatural, seasons
        self._economy()
        self._debts_and_contracts()
        self._supernatural()
        self._season_tick()
        self._diplomacy_drift()
        self._check_elimination()
        self.turn += 1
        self._check_victory()

        self.last_events = self._turn_events
        self.snapshots.append(self.snapshot())
        done = self.winner is not None or self.turn >= self.max_turns
        if done and self.winner is None:
            contenders = [f for f in self.alive() if self.kind(f) in ("house", "horde", "tribe")] or self.alive()
            best = max(contenders, key=self.power)
            self.winner, self.win_reason = best, "most powerful when the chronicle ends"
            self.log("game_over", winner=best, reason=self.win_reason)
        rewards = {f: self.power(f) - before.get(f, 0) for f in self.faction_ids}
        obs = {f: self.observe(f) for f in self.alive()}
        return obs, rewards, done, dict(events=self._turn_events, winner=self.winner)

    # ---------------------------------------------------------------- actions
    def _recruit(self, fid, a):
        r, n = a["region"], int(a["n"])
        if self.owner.get(r) != fid or n <= 0 or self.kind(fid) in ("undead",):
            raise ValueError("cannot recruit there")
        n = min(n, REGIONS[r]["levy"])
        s = self.f[fid]
        if self.kind(fid) == "tribe":
            n = int(min(n, s["food"] / (RECRUIT_COST * 1.5)))
            s["food"] -= n * RECRUIT_COST * 1.5
        else:
            n = int(min(n, s["gold"] / RECRUIT_COST))
            s["gold"] -= n * RECRUIT_COST
        if n > 0:
            self.garrison[r][fid] += n
            self.log("recruit", by=fid, region=r, n=n)

    def _propose(self, fid, a):
        if a["type"] == "hire": a = dict(a, to="golden_company")
        to = a["to"]
        if to not in self.f or not self.f[to]["alive"] or to == fid:
            raise ValueError("bad recipient")
        kind = a["type"]
        if kind == "lend" and fid != "iron_bank": raise ValueError("only the Iron Bank lends")
        if kind == "request_loan" and fid in self.blacklist: raise ValueError("blacklisted by the Iron Bank")
        if kind == "request_loan" and self.kind(fid) not in ("house", "sellsword", "horde"):
            raise ValueError("the Iron Bank does not lend to the likes of you")
        self._pid += 1
        pid = f"p{self._pid}"
        p = dict(id=pid, kind=kind, **{"from": fid}, to=to,
                 **{k: v for k, v in a.items() if k not in ("type", "to")})
        self.proposals[pid] = p
        self.log("proposal", by=fid, to=to, kind=kind, id=pid,
                 detail={k: v for k, v in p.items() if k not in ("id", "kind", "from", "to")})

    def _resolve(self, p, ok):
        a, b, k = p["from"], p["to"], p["kind"]
        if not (self.f[a]["alive"] and self.f[b]["alive"]):
            return
        self.log("accepted" if ok else "rejected", by=b, to=a, kind=k, id=p["id"])
        if not ok:
            self.shift_rel(a, b, -3)
            return
        if k in ("propose_alliance", "propose_marriage"):
            if self.kind(a) == "undead" or self.kind(b) == "undead":
                return
            wed = k == "propose_marriage" and _pair(a, b) not in self.married
            if self.allied(a, b) and not wed:
                return
            if not self.allied(a, b):
                self.allies.add(_pair(a, b)); self.alliance_start[_pair(a, b)] = self.turn
            self.shift_rel(a, b, 15)
            if wed:
                self.married.add(_pair(a, b)); self.shift_rel(a, b, 20)
            self.log("alliance_formed", a=a, b=b, marriage=wed)
        elif k == "propose_trade":
            give, get = p.get("give", {}), p.get("get", {})
            if all(self.f[a][r] >= float(v) for r, v in give.items()) and \
               all(self.f[b][r] >= float(v) for r, v in get.items()):
                for r, v in give.items(): self.f[a][r] -= float(v); self.f[b][r] += float(v)
                for r, v in get.items(): self.f[b][r] -= float(v); self.f[a][r] += float(v)
                self.shift_rel(a, b, 5)
                self.log("trade", a=a, b=b, give=give, get=get)
            else:
                self.log("trade_failed", a=a, b=b, reason="insufficient resources")
        elif k == "request_loan":
            amt = float(p.get("amount", 0))
            if 0 < amt <= self.f["iron_bank"]["gold"]:
                self._make_loan(a, amt)
        elif k == "lend":  # iron bank offered, recipient accepted
            amt = float(p.get("amount", 0))
            if 0 < amt <= self.f["iron_bank"]["gold"]:
                self._make_loan(b, amt)
        elif k == "hire":
            n, price, turns, region = int(p["n"]), float(p["price"]), int(p.get("turns", 5)), p["region"]
            n = min(n, self.troops("golden_company"))
            if n > 0 and self.owner.get(region) == a:
                self._take_troops("golden_company", n)
                self.garrison[region][a] += n
                self.contracts.append(dict(hirer=a, n=n, price=price, until=self.turn + turns, region=region))
                self.log("sellswords_hired", hirer=a, n=n, price=price, turns=turns, region=region)

    def _make_loan(self, borrower, amt):
        self.f["iron_bank"]["gold"] -= amt
        self.f[borrower]["gold"] += amt
        self.loans.append(dict(borrower=borrower, owed=amt * (1 + LOAN_INTEREST), due=self.turn + LOAN_TERM))
        self.log("loan", borrower=borrower, amount=amt, due=self.turn + LOAN_TERM)

    def _break(self, fid, to):
        p = _pair(fid, to)
        if p in self.allies:
            self.allies.discard(p)
            wed = p in self.married
            self.married.discard(p)
            self._broken_this_turn.add((fid, to))
            if wed: self._broken_married.add((fid, to))
            self.shift_rel(fid, to, -40 if wed else -25)
            self.f[fid]["reputation"] -= 10 if wed else 5
            self.log("alliance_broken", by=fid, to=to, marriage=wed,
                     duration=self.turn - self.alliance_start.get(p, 0))

    def _repay(self, fid, amt):
        for l in self.loans:
            if l["borrower"] == fid and amt > 0:
                pay = min(amt, l["owed"], self.f[fid]["gold"])
                l["owed"] -= pay; amt -= pay
                self.f[fid]["gold"] -= pay; self.f["iron_bank"]["gold"] += pay
                if pay > 0: self.log("repayment", by=fid, amount=round(pay, 1))
        self.loans = [l for l in self.loans if l["owed"] > 0.01]

    def _fund(self, fid, a):
        to, amt = a["to"], float(a["amount"])
        amt = min(amt, self.f[fid]["gold"])
        if to in self.f and self.f[to]["alive"] and amt > 0 and to != fid:
            self.f[fid]["gold"] -= amt; self.f[to]["gold"] += amt
            self.shift_rel(fid, to, 8)
            self.log("funding", by=fid, to=to, amount=round(amt, 1))

    def _raven(self, fid, a):
        text = str(a.get("text", ""))[:500]
        targets = self.alive() if a.get("to") == "all" else [a["to"]]
        for t in targets:
            if t != fid and t in self.f:
                self.ravens[t].append(dict(**{"from": fid}, text=text))
        self.log("raven", by=fid, to=a.get("to"), text=text)

    # --------------------------------------------------------------- military
    def _is_peaceful(self, fid, a):
        o = self.owner.get(a.get("dst"))
        return a.get("type") == "move" and (o == fid or (o is not None and self.allied(fid, o)))

    def _take_troops(self, fid, n):
        """Remove n troops of fid from wherever they are (largest garrisons first)."""
        for r in sorted(REGIONS, key=lambda r: -self.garrison[r].get(fid, 0)):
            take = min(n, self.garrison[r].get(fid, 0))
            self.garrison[r][fid] -= take; n -= take
            if n <= 0: break

    def _strength_mult(self, fid, attacking, region, by_sea):
        m = 1.0
        if fid == "baratheon": m *= 1.2
        if fid == "greyjoy" and attacking and by_sea: m *= 1.15
        if fid == "dothraki" and attacking and REGIONS[region]["defense"] < 1.5: m *= 1.3
        if fid == "martell" and not attacking and region == "dorne": m *= 1.4
        if fid == "white_walkers" and self.season == "winter": m *= 1.2
        if fid in ("stark", "nights_watch") and self._vs_dead: m *= 1.5   # dragonglass & Valyrian steel
        if attacking and by_sea and fid not in ("greyjoy",): m *= 0.8   # amphibious landings are hard
        return m

    def _move(self, fid, a):
        src, dst, n = a["src"], a["dst"], int(a["n"])
        # src == dst: turn on the hosts whose region your troops are standing in (a Red Wedding)
        edge = "land" if (src == dst and self.owner[dst] != fid) else self.adj[src].get(dst)
        have = self.garrison[src].get(fid, 0)
        n = min(n, have)
        if edge is None or n <= 0:
            raise ValueError(f"illegal move {src}->{dst}")
        if edge == "sea" and fid != "white_walkers":
            if self.ships_available(fid) * SHIPS_PER_TROOPS < n:
                n = self.ships_available(fid) * SHIPS_PER_TROOPS
                if n <= 0: raise ValueError("no ships for sea crossing")
        if fid == "white_walkers" and edge == "sea":
            raise ValueError("the dead do not sail")
        o = self.owner[dst]
        if a["type"] == "raid":
            return self._raid(fid, src, dst, n, edge)
        if o == fid or (o is not None and self.allied(fid, o)):
            self.garrison[src][fid] -= n
            self.garrison[dst][fid] += n
            self.log("move", by=fid, src=src, dst=dst, n=n, by_sea=edge == "sea")
            return
        # ---- attack
        if self.kind(fid) in ("bank",):
            raise ValueError("the Iron Bank does not march")
        if fid == "nights_watch" and o not in (None, "free_folk", "white_walkers"):
            raise ValueError("the Night's Watch takes no part in the wars of the realm")
        if fid == "white_walkers" and self.season != "winter":
            raise ValueError("the dead only march in winter")
        if dst == "lands_of_always_winter" and fid != "white_walkers":
            raise ValueError("no living army survives the Lands of Always Winter")
        self._battle(fid, src, dst, n, edge)

    def _battle(self, fid, src, dst, n, edge):
        o = self.owner[dst]
        defenders = {k: v for k, v in self.garrison[dst].items() if v > 0 and k != fid and
                     (k == o or k == "neutral" or (o is not None and k in self.f and self.allied(k, o)))}
        if o in self.f and (fid, o) in self._broken_this_turn:
            wed = (fid, o) in self._broken_married
            self.f[fid]["reputation"] -= 15
            for other in self.alive():
                if other not in (fid, o): self.shift_rel(fid, other, -8)
            self.log("red_wedding" if wed else "betrayal", by=fid, victim=o, region=dst)
        self._vs_dead = "white_walkers" in (fid, o)
        att = n * self._strength_mult(fid, True, dst, edge == "sea") * self.rng.uniform(0.8, 1.2)
        fire = 2 if self._vs_dead else 1   # dragonfire burns the dead
        dragons_here = 0
        if "targaryen" in (fid, o) and not self._dragons_used:   # dragons fight one battle per turn
            dragons_here = self.f["targaryen"]["dragons"]
            if dragons_here: self._dragons_used = True
        if fid == "targaryen": att += dragons_here * self.dragon_power() * fire
        d_raw = sum(defenders.values())
        dfn = sum(v * (self._strength_mult(k, False, dst, False) if k in self.f else 1.0)
                  for k, v in defenders.items()) * REGIONS[dst]["defense"] * self.rng.uniform(0.8, 1.2)
        if o == "targaryen": dfn += dragons_here * self.dragon_power() * fire
        ratio = att / max(1e-6, att + dfn)
        att_loss = int(n * (1 - ratio) * 0.7)
        def_loss_frac = ratio * 0.7
        win = att > dfn
        dragons_lost = 0
        if dragons_here:
            enemy_strength = dfn if fid == "targaryen" else att
            for _ in range(dragons_here):
                if self.rng.random() < min(0.35, 0.04 * enemy_strength / 3000):
                    dragons_lost += 1
            self.f["targaryen"]["dragons"] -= dragons_lost
        survivors = n - att_loss
        self.garrison[src][fid] -= n
        def_losses = {}
        for k, v in defenders.items():
            lost = v if win else int(v * def_loss_frac)   # on defeat the garrison is slain or scattered
            def_losses[k] = lost
            self.garrison[dst][k] -= lost
        if win:
            self.owner[dst] = fid
            self.garrison[dst][fid] += survivors
        else:
            self.garrison[src][fid] += survivors
        if fid == "white_walkers":  # the dead rise
            raised = int(sum(def_losses.values()) * 0.5)
            self.garrison[dst if win else src]["white_walkers"] += raised
        if o in self.f:
            self.shift_rel(fid, o, -35)
            for other in self.alive():
                if other not in (fid, o) and self.allied(other, o):
                    self.shift_rel(fid, other, -10)
        self.log("battle", attacker=fid, defender=o or "neutral", region=dst, src=src, troops=n,
                 defenders=d_raw, attacker_won=win, attacker_losses=att_loss,
                 defender_losses=sum(def_losses.values()), dragons_lost=dragons_lost,
                 by_sea=edge == "sea", conquered=win)
        if win and dst == "crownlands":
            self.log("throne_seized", by=fid, previous=o)

    def _raid(self, fid, src, dst, n, edge):
        if fid not in ("greyjoy", "free_folk", "dothraki"):
            raise ValueError("only reavers, wildlings and horse lords raid")
        o = self.owner[dst]
        if o is None or o == fid or self.allied(fid, o):
            raise ValueError("nothing to raid")
        local = sum(v for k, v in self.garrison[dst].items() if k == o)
        self._vs_dead = "white_walkers" in (fid, o)
        att = n * self._strength_mult(fid, True, dst, edge == "sea") * self.rng.uniform(0.7, 1.3)
        dfn = local * 0.6 * self.rng.uniform(0.7, 1.3)   # raids hit before defenders can concentrate
        ratio = att / max(1e-6, att + dfn)
        loss = int(n * (1 - ratio) * 0.4)
        self.garrison[src][fid] -= loss
        self.garrison[dst][o] = max(0, local - int(local * ratio * 0.15))
        stolen_food = stolen_gold = 0.0
        if att > dfn:
            stolen_food = min(self.f[o]["food"], REGIONS[dst]["food"] * INCOME_SCALE * 1.5)
            stolen_gold = min(self.f[o]["gold"], REGIONS[dst]["gold"] * INCOME_SCALE * 1.5)
            self.f[o]["food"] -= stolen_food; self.f[fid]["food"] += stolen_food
            self.f[o]["gold"] -= stolen_gold; self.f[fid]["gold"] += stolen_gold
        self.shift_rel(fid, o, -20)
        self.log("raid", by=fid, target=o, region=dst, src=src, troops=n, by_sea=edge == "sea", success=att > dfn, losses=loss,
                 food=round(stolen_food, 1), gold=round(stolen_gold, 1))

    # ---------------------------------------------------------------- economy
    def _economy(self):
        winter = self.season == "winter"
        for fid in self.alive():
            s = self.f[fid]
            if self.kind(fid) == "undead":
                continue
            food = gold = 0.0
            for r in self.regions_of(fid):
                R = REGIONS[r]
                fm = (0.35 if R["y"] < 420 else 0.65) if winter else 1.0
                food += R["food"] * INCOME_SCALE * fm
                gold += R["gold"] * INCOME_SCALE
            if fid == "lannister": gold *= 1.5
            if fid == "tyrell": food *= 1.3
            if fid == "tully": food *= 1.2
            if self.owner["crownlands"] == fid: gold += 30   # crown taxes
            if fid == "iron_bank": gold += 20                # interest on the world
            upkeep = self.troops(fid) * FOOD_PER_TROOP * (0.5 if fid == "stark" and winter else 1.0)
            s["food"] += food - upkeep
            s["gold"] += gold
            if fid == "nights_watch":
                self.garrison["the_wall"]["nights_watch"] += 40 if self.owner["the_wall"] == "nights_watch" else 0
            if s["food"] < 0:  # starvation: desertion
                deserters = int(self.troops(fid) * 0.12)
                self._take_troops(fid, deserters)
                self.log("starvation", faction=fid, deserters=deserters)
                s["food"] = 0.0

    def _debts_and_contracts(self):
        keep = []
        for l in self.loans:
            if self.turn >= l["due"]:
                b = self.f[l["borrower"]]
                pay = min(b["gold"], l["owed"])
                b["gold"] -= pay; self.f["iron_bank"]["gold"] += pay; l["owed"] -= pay
                if l["owed"] > 0.01:
                    self.blacklist.add(l["borrower"])
                    self.f[l["borrower"]]["reputation"] -= 10
                    self.shift_rel("iron_bank", l["borrower"], -50)
                    self.log("default", borrower=l["borrower"], unpaid=round(l["owed"], 1))
                else:
                    self.log("loan_repaid", borrower=l["borrower"])
            else:
                keep.append(l)
        self.loans = keep
        keep = []
        for c in self.contracts:
            h = c["hirer"]
            if not self.f[h]["alive"]:
                continue
            if self.turn >= c["until"] or self.f[h]["gold"] < c["price"]:
                n = min(c["n"], self.troops(h))
                self._take_troops(h, n)
                self.garrison[self.regions_of("golden_company")[0] if self.regions_of("golden_company") else "free_cities"]["golden_company"] += n
                broke = self.turn < c["until"]
                if broke: self.shift_rel(h, "golden_company", -20)
                self.log("contract_ended", hirer=h, n=n, unpaid=broke)
            else:
                self.f[h]["gold"] -= c["price"]; self.f["golden_company"]["gold"] += c["price"]
                keep.append(c)
        self.contracts = keep

    def _supernatural(self):
        if "white_walkers" not in self.f or not self.f["white_walkers"]["alive"]:
            return
        for r in self.regions_of("white_walkers"):
            g = self.garrison[r]
            if self.season == "winter":
                g["white_walkers"] += int(g["white_walkers"] * 0.05) + 40
            elif r == "lands_of_always_winter":
                g["white_walkers"] += 15
            else:  # summer sun: the dead wither south of the Wall
                lost = int(g["white_walkers"] * 0.15)
                g["white_walkers"] -= lost
                if g["white_walkers"] <= 50:
                    g["white_walkers"] = 0
                    self.owner[r] = None
                    self.log("dead_retreat", region=r)

    def _season_tick(self):
        self.season_left -= 1
        if self.season_left <= 0:
            self.season = "winter" if self.season == "summer" else "summer"
            self.season_left = self.rng.randint(15, 25) if self.season == "winter" else self.rng.randint(25, 40)
            self.log("season", season=self.season,
                     text="Winter has come." if self.season == "winter" else "Spring returns to Westeros.")

    def _diplomacy_drift(self):
        for a, b in list(self.allies):
            self.shift_rel(a, b, 1)
        # a common enemy at the Wall slowly brings the living together in winter
        if self.season == "winter" and self.owner["the_wall"] == "white_walkers":
            living = [f for f in self.alive() if f != "white_walkers"]
            for i, a in enumerate(living):
                for b in living[i + 1:]:
                    self.shift_rel(a, b, 1)
        # whoever sits the Iron Throne is envied by everyone else
        holder = self.owner["crownlands"]
        if holder in self.f:
            for o in self.alive():
                if o != holder and not self.allied(o, holder) and self.kind(o) == "house":
                    self.shift_rel(o, holder, -2)
        # border incidents: neighbours with different lords grate on each other
        borders = {_pair(self.owner[a], self.owner[b]) for a in REGIONS for b in self.adj[a]
                   if self.owner[a] in self.f and self.owner[b] in self.f and self.owner[a] != self.owner[b]
                   and self.kind(self.owner[a]) in ("house", "horde", "tribe", "order")
                   and self.kind(self.owner[b]) in ("house", "horde", "tribe", "order")}
        for a, b in sorted(borders):
            if self.rng.random() < 0.10:
                d = -self.rng.randint(5, 20)
                self.shift_rel(a, b, d)
                self.log("border_incident", a=a, b=b, delta=d)
        for fid in self.alive():
            s = self.f[fid]
            target = 50 + 30 * FACTIONS[fid]["traits"]["honor"]
            s["reputation"] += (target - s["reputation"]) * 0.02

    def _check_elimination(self):
        for fid in self.alive():
            if not self.regions_of(fid) and self.troops(fid) <= 0:
                self.f[fid]["alive"] = False
                self.f[fid]["eliminated_turn"] = self.turn
                self.allies = {p for p in self.allies if fid not in p}
                self.log("eliminated", faction=fid)
            elif not self.regions_of(fid) and self.kind(fid) not in ("undead",):
                # landless remnants wander; they starve faster
                pass
        for r, g in self.garrison.items():
            for k in list(g):
                if g[k] <= 0: del g[k]

    def _check_victory(self):
        holder = self.owner["crownlands"]
        for fid in self.alive():
            self.f[fid]["throne_turns"] = self.f[fid]["throne_turns"] + 1 if holder == fid else 0
        if holder and self.kind(holder) == "house" and len(self.regions_of(holder)) < THRONE_MIN_REGIONS:
            self.f[holder]["throne_turns"] = 0   # a king who rules only his city is no king
        if holder and self.kind(holder) == "house" and self.f[holder]["throne_turns"] >= THRONE_TURNS:
            self.winner, self.win_reason = holder, f"ruled the Seven Kingdoms from the Iron Throne for {THRONE_TURNS} turns"
        if "white_walkers" in self.f and len(self.regions_of("white_walkers")) >= LONG_NIGHT_REGIONS:
            self.winner, self.win_reason = "white_walkers", "the Long Night has fallen"
        if self.winner:
            self.log("game_over", winner=self.winner, reason=self.win_reason)

    # --------------------------------------------------------------- logging
    def snapshot(self):
        return dict(
            turn=self.turn, season=self.season,
            owner=dict(self.owner),
            garrison={r: {k: v for k, v in g.items() if v > 0} for r, g in self.garrison.items()},
            factions={f: dict(alive=s["alive"], gold=round(s["gold"], 1), food=round(s["food"], 1),
                              troops=self.troops(f), regions=len(self.regions_of(f)), dragons=s["dragons"],
                              reputation=round(s["reputation"], 1), power=round(self.power(f), 1))
                      for f, s in self.f.items()},
            allies=sorted(list(p) for p in self.allies),
            married=sorted(list(p) for p in self.married),
            relations={f"{a}|{b}": v for (a, b), v in self.rel.items()},
            events=list(getattr(self, "_turn_events", [])),
        )
