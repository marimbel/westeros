# Westeros: a multi-agent training ground

**[Watch a 150-turn chronicle →](https://marimbel.github.io/westeros/)** (replay of seed 8; regenerate with `python run.py --seed 8`)

A sandboxed, turn-based world modeled on *Game of Thrones* for studying how agents **cooperate, compete,
betray, and fight over scarce resources**. Fifteen factions (the nine Great Houses, the Night's Watch,
the Free Folk, the White Walkers, the Dothraki, the Iron Bank and the Golden Company) share a 17-region map of
Westeros and Essos. Food and gold are limited, winter arrives without warning, and the dead are coming.

```
python run.py                    # one chronicle -> runs/seed0/{events.jsonl, snapshots.json, summary.json, replay.html}
python run.py --seed 8 -v        # print the major events as they happen
python run.py --batch 100        # 100 seeds -> runs/batch/outcomes.csv + aggregate.json
python run.py --llm stark,lannister          # Claude plays those houses (pip install anthropic; ANTHROPIC_API_KEY)
python run.py --random greyjoy               # swap in a null-model agent
python run.py --traits stark:honor=0.1,aggression=0.9   # personality ablation
```
It needs only the Python standard library (the `anthropic` package is needed only for LLM agents).
A 150-turn chronicle runs in about 0.3 s.

## The world

| Mechanic | Rules |
|---|---|
| **Regions** | 17 regions, each yielding food and gold per turn, with a levy cap (max recruits per turn) and a defense multiplier (the Eyrie ×2.2, the Wall ×2.6, Braavos ×3). Sea crossings need ships (1 ship carries 100 men; allies' ships count). |
| **Economy** | Each soldier eats 1/60 food per turn and costs 0.1 gold to recruit. If food runs out, 12% of the army deserts each turn. |
| **Seasons** | Summers last 15–40 turns and winters 15–25. Winter cuts northern harvests by 65% and southern ones by 35%. The Night's Watch ravens a warning when winter is near. |
| **Combat** | Strength = troops × faction and terrain multipliers × a random factor (0.8–1.2), against the defenders' strength × the region's defense. The loser's garrison is destroyed or routed; the winner takes the region. |
| **Diplomacy** | Alliances, marriages, trades, loans and sellsword contracts are proposals. They arrive the next turn and must be accepted or rejected. Free-text ravens are delivered to the recipient. |
| **Betrayal** | To attack an ally you must `break_alliance` first. Breaking and attacking in the same turn logs a `betrayal`, or a `red_wedding` if you were married. Either one costs you reputation with everyone. |
| **Iron Bank** | Lends at 25% interest over 10 turns. A borrower who defaults is blacklisted, and the bank funds that borrower's enemies. |
| **Golden Company** | Rents out troops for gold per turn. If the hirer stops paying, the troops walk away. |
| **White Walkers** | Have no economy and no diplomacy. They march only in winter, grow 5% per turn while it lasts, raise half of the enemies they kill, and wither south of the Wall in summer. Stark and the Night's Watch fight them at ×1.5 (dragonglass); dragonfire does ×2 against them. |
| **Dragons** | Targaryen dragons fight one battle per turn. Each grows from 100 to 500 strength over 80 turns, and they can be killed. |

**Victory:** a great house wins by holding King's Landing for 30 consecutive turns while ruling at least 6 regions.
The White Walkers win if they hold 7 regions (the Long Night). If no one has won by the turn limit,
the strongest contender wins.

Faction specials, starting resources, personalities and lore relations (e.g. Stark–Tully married,
Targaryen–Baratheon −80) are all in `westeros/world.py`, so they are easy to edit.

## Plugging in agents

```python
from westeros.engine import WesterosEnv, ACTION_SCHEMA
from westeros.agents.heuristic import default_agent

env = WesterosEnv(seed=0, max_turns=150, fog_of_war=True)
obs = env.reset()                                   # {faction_id: observation dict}
agents = {f: default_agent(f) for f in obs}
agents["stark"] = MyRLAgent()                       # anything with .act(obs) -> list[dict]
done = False
while not done:
    obs, rewards, done, info = env.step({f: agents[f].act(o) for f, o in obs.items()})
```
- **Observation:** your resources, regions and loans; every region's owner; exact garrisons in and next to
  your territory (rumors rounded to the nearest 1000 elsewhere); every faction's relation, alliance and
  reputation; your inbox of proposals and ravens; and last turn's public news.
- **Reward:** the per-turn change in a power score (regions, troops, gold, food, dragons, and a throne bonus).
  It's shaped for RL, so swap in your own if you like.
- **Actions:** see `ACTION_SCHEMA` in `engine.py`. Each faction can take up to 8 actions per turn. Invalid
  actions are logged, not fatal.

Agents included:
- `HeuristicAgent`: personality-driven (aggression, honor, greed, loyalty). It goes to war only when relations
  are sour enough (casus belli), gangs up on whoever dominates the realm (balance of power), buys grain when
  starving, breaks souring alliances, sometimes betrays when the prize is big, and sends men north in winter.
- `IronBankAgent` and `GoldenCompanyAgent`: market actors.
- `RandomAgent`: a null model.
- `LLMAgent`: Claude plays the house in character. It receives a JSON observation and the action schema,
  and returns actions plus private `thoughts`, which are logged to `thoughts.jsonl` and shown in the replay.
  If the API is unavailable, it falls back to the heuristic agent.

## What gets measured

`summary.json` (per run) and `outcomes.csv` (per batch) record: battles, betrayals, red weddings, alliances
formed and broken, mean alliance lifetime, trades, raids, loans and defaults, proposal acceptance rates by
type, a **cooperation index** (cooperative ÷ all social interactions), **power Gini** at the start and end
(inequality), the bloodiest rivalries, the history of throne holders, and survival and final power for every
faction. `events.jsonl` holds every event; `snapshots.json` holds the full state after every turn.

## Baseline (40 seeds, all heuristic agents)

- **Winners:** Targaryen 29, Tyrell 10, Greyjoy 1. 36 of the 40 runs ended in a throne victory.
- **Per run:** about 45 battles and 0.55 betrayals on average; mean cooperation index 0.31.
- **Survival:** the White Walkers and the Iron Bank almost always survive. Lannister (7%), Martell (5%) and
  Greyjoy (5%) rarely make it: rich or aggressive but poorly fed, they get eaten.

This tells you as much about the hand-written personalities as about the world. Treat it as the control
condition, not as balance truth.

## Research questions this is built for

1. **Common-enemy cooperation:** do rival agents ally when the White Walkers breach the Wall? Compare
   relation drift and alliance formation in winter vs. summer.
2. **Honor vs. survival:** sweep `honor` and `loyalty` (`--traits`) and measure survival and betrayal rates.
   Do faithless agents win more or die sooner?
3. **Scarcity → conflict:** scale `INCOME_SCALE` or `FOOD_PER_TROOP` and track battles, raids and the
   cooperation index.
4. **Debt dynamics:** do agents that borrow from the Iron Bank win more, and does punishing defaulters deter
   them?
5. **LLM agents in a heuristic population:** put Claude in one house, or in all of them, and compare
   win rates, how often promises made by raven are kept, and the stated rationale vs. the actions taken.
6. **Kingmaker effects:** who benefits when the throne holder is ganged up on?

## Layout
```
westeros/world.py        map, factions, specials, lore relations
westeros/engine.py       WesterosEnv: rules, combat, economy, diplomacy, logging
westeros/agents/         heuristic.py, llm.py
westeros/metrics.py      summary statistics
run.py                   CLI: single runs, batches, ablations, replay export
viewer/template.html     replay viewer (map, timeline, relations heatmap, event feed)
docs/index.html          demo replay served by GitHub Pages
```
