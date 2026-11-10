"""Static world definition for the Westeros sandbox: regions, map edges, factions, lore relations.

Units: region `food`/`gold` are per-turn yields (multiplied by INCOME_SCALE in the engine),
`levy` is the max troops recruitable there per turn, `defense` multiplies defender strength.
"""

INCOME_SCALE = 10

REGIONS = {
    "lands_of_always_winter": dict(name="Lands of Always Winter", seat="Heart of Winter", x=400, y=35,  food=0, gold=0,  levy=0,   defense=1.0, coastal=False),
    "haunted_forest":         dict(name="Haunted Forest",         seat="Hardhome",        x=490, y=100, food=3, gold=0,  levy=150, defense=1.0, coastal=True),
    "the_wall":               dict(name="The Wall",               seat="Castle Black",    x=440, y=165, food=3, gold=0,  levy=60,  defense=2.6, coastal=False),
    "the_north":              dict(name="The North",              seat="Winterfell",      x=390, y=265, food=4, gold=2,  levy=400, defense=1.4, coastal=True),
    "the_vale":               dict(name="The Vale",               seat="The Eyrie",       x=580, y=375, food=3, gold=3,  levy=250, defense=2.2, coastal=True),
    "riverlands":             dict(name="The Riverlands",         seat="Riverrun",        x=430, y=400, food=5, gold=3,  levy=350, defense=1.3, coastal=True),
    "iron_islands":           dict(name="The Iron Islands",       seat="Pyke",            x=240, y=365, food=1, gold=1,  levy=200, defense=1.6, coastal=True),
    "westerlands":            dict(name="The Westerlands",        seat="Casterly Rock",   x=290, y=475, food=3, gold=8,  levy=300, defense=1.6, coastal=True),
    "crownlands":             dict(name="The Crownlands",         seat="King's Landing",  x=540, y=505, food=3, gold=6,  levy=300, defense=1.3, coastal=True, throne=True),
    "dragonstone":            dict(name="Dragonstone",            seat="Dragonstone",     x=650, y=455, food=1, gold=1,  levy=50,  defense=1.8, coastal=True),
    "the_reach":              dict(name="The Reach",              seat="Highgarden",      x=340, y=615, food=7, gold=5,  levy=450, defense=1.2, coastal=True),
    "stormlands":             dict(name="The Stormlands",         seat="Storm's End",     x=570, y=615, food=3, gold=2,  levy=300, defense=1.7, coastal=True),
    "dorne":                  dict(name="Dorne",                  seat="Sunspear",        x=480, y=745, food=2, gold=3,  levy=250, defense=1.5, coastal=True),
    "braavos":                dict(name="Braavos",                seat="The Iron Bank",   x=800, y=255, food=3, gold=10, levy=50,  defense=3.0, coastal=True),
    "free_cities":            dict(name="The Free Cities",        seat="Pentos",          x=810, y=470, food=3, gold=5,  levy=200, defense=1.5, coastal=True),
    "dothraki_sea":           dict(name="The Dothraki Sea",       seat="Vaes Dothrak",    x=950, y=400, food=3, gold=0,  levy=500, defense=1.0, coastal=False),
    "slavers_bay":            dict(name="Slaver's Bay",           seat="Meereen",         x=940, y=640, food=3, gold=4,  levy=300, defense=1.4, coastal=True),
}

LAND_EDGES = [
    ("lands_of_always_winter", "haunted_forest"), ("haunted_forest", "the_wall"), ("the_wall", "the_north"),
    ("the_north", "riverlands"), ("riverlands", "the_vale"), ("riverlands", "westerlands"),
    ("riverlands", "crownlands"), ("riverlands", "the_reach"), ("westerlands", "the_reach"),
    ("the_reach", "crownlands"), ("the_reach", "stormlands"), ("the_reach", "dorne"),
    ("crownlands", "stormlands"), ("stormlands", "dorne"), ("the_vale", "crownlands"),
    ("braavos", "free_cities"), ("free_cities", "dothraki_sea"), ("dothraki_sea", "slavers_bay"),
    ("free_cities", "slavers_bay"),
]
SEA_EDGES = [
    ("iron_islands", "the_north"), ("iron_islands", "riverlands"), ("iron_islands", "westerlands"),
    ("iron_islands", "the_reach"), ("crownlands", "dragonstone"), ("dragonstone", "stormlands"),
    ("dragonstone", "free_cities"), ("the_vale", "braavos"), ("the_north", "braavos"),
    ("the_vale", "the_north"), ("crownlands", "free_cities"), ("dorne", "free_cities"),
    ("dorne", "slavers_bay"), ("haunted_forest", "the_north"),
]

# kind: house | order (Night's Watch) | tribe | undead | horde | bank | sellsword
FACTIONS = {
    "stark":          dict(name="House Stark",      motto="Winter is Coming",               kind="house",     color="#8395a7", regions=["the_north"],                troops=2000, gold=60,   food=160, ships=5,  dragons=0, traits=dict(aggression=0.35, honor=0.95, greed=0.2, loyalty=0.9)),
    "lannister":      dict(name="House Lannister",  motto="A Lannister always pays his debts", kind="house",  color="#c0392b", regions=["westerlands"],              troops=2500, gold=320,  food=100, ships=10, dragons=0, traits=dict(aggression=0.6,  honor=0.3,  greed=0.85, loyalty=0.5)),
    "baratheon":      dict(name="House Baratheon",  motto="Ours is the Fury",               kind="house",     color="#f1c40f", regions=["crownlands", "stormlands"], troops=3000, gold=80,   food=120, ships=15, dragons=0, traits=dict(aggression=0.7,  honor=0.6,  greed=0.4,  loyalty=0.6)),
    "targaryen":      dict(name="House Targaryen",  motto="Fire and Blood",                 kind="house",     color="#8e44ad", regions=["slavers_bay"],              troops=1200, gold=100,  food=90,  ships=20, dragons=3, traits=dict(aggression=0.7,  honor=0.6,  greed=0.5,  loyalty=0.65)),
    "tyrell":         dict(name="House Tyrell",     motto="Growing Strong",                 kind="house",     color="#27ae60", regions=["the_reach"],                troops=2500, gold=200,  food=320, ships=10, dragons=0, traits=dict(aggression=0.3,  honor=0.5,  greed=0.6,  loyalty=0.5)),
    "greyjoy":        dict(name="House Greyjoy",    motto="We Do Not Sow",                  kind="house",     color="#16a3b8", regions=["iron_islands"],             troops=1500, gold=50,   food=60,  ships=60, dragons=0, traits=dict(aggression=0.9,  honor=0.2,  greed=0.7,  loyalty=0.3)),
    "martell":        dict(name="House Martell",    motto="Unbowed, Unbent, Unbroken",      kind="house",     color="#e67e22", regions=["dorne"],                    troops=1800, gold=120,  food=90,  ships=10, dragons=0, traits=dict(aggression=0.35, honor=0.6,  greed=0.4,  loyalty=0.6)),
    "arryn":          dict(name="House Arryn",      motto="As High as Honor",               kind="house",     color="#4a69bd", regions=["the_vale"],                 troops=1800, gold=120,  food=120, ships=10, dragons=0, traits=dict(aggression=0.2,  honor=0.8,  greed=0.3,  loyalty=0.6)),
    "tully":          dict(name="House Tully",      motto="Family, Duty, Honor",            kind="house",     color="#2e86de", regions=["riverlands"],               troops=1800, gold=80,   food=170, ships=0,  dragons=0, traits=dict(aggression=0.3,  honor=0.85, greed=0.3,  loyalty=0.9)),
    "nights_watch":   dict(name="The Night's Watch", motto="I am the sword in the darkness", kind="order",    color="#222222", regions=["the_wall"],                 troops=900,  gold=10,   food=80,  ships=2,  dragons=0, traits=dict(aggression=0.1,  honor=0.9,  greed=0.0,  loyalty=0.8)),
    "free_folk":      dict(name="The Free Folk",    motto="We bow to no king",              kind="tribe",     color="#8d6e63", regions=["haunted_forest"],           troops=2500, gold=0,    food=60,  ships=0,  dragons=0, traits=dict(aggression=0.6,  honor=0.5,  greed=0.5,  loyalty=0.6)),
    "white_walkers":  dict(name="The White Walkers", motto="(silence)",                     kind="undead",    color="#74b9ff", regions=["lands_of_always_winter"],   troops=1200, gold=0,    food=0,   ships=0,  dragons=0, traits=dict(aggression=1.0,  honor=0.0,  greed=0.0,  loyalty=1.0)),
    "dothraki":       dict(name="The Dothraki",     motto="It is known",                    kind="horde",     color="#a0522d", regions=["dothraki_sea"],             troops=4000, gold=0,    food=100, ships=0,  dragons=0, traits=dict(aggression=0.85, honor=0.5,  greed=0.6,  loyalty=0.75)),
    "iron_bank":      dict(name="The Iron Bank of Braavos", motto="The Iron Bank will have its due", kind="bank", color="#57606f", regions=["braavos"],          troops=1200,  gold=1200, food=100, ships=20, dragons=0, traits=dict(aggression=0.0,  honor=0.7,  greed=0.9,  loyalty=0.5)),
    "golden_company": dict(name="The Golden Company", motto="Beneath the gold, the bitter steel", kind="sellsword", color="#b7950b", regions=["free_cities"], troops=2200, gold=60, food=90, ships=10, dragons=0, traits=dict(aggression=0.4, honor=0.4, greed=0.95, loyalty=0.3)),
}

# Special abilities applied by the engine (kept here so they are easy to read/tweak).
SPECIALS = {
    "stark":          "Winter-hardened: food upkeep halved in winter.",
    "lannister":      "Gold of Casterly Rock: +50% gold income.",
    "baratheon":      "Ours is the Fury: +20% combat strength.",
    "targaryen":      "Dragons: fight one battle per turn, growing from 100 to 500 strength each (x2 vs the dead); can be slain.",
    "tyrell":         "Breadbasket: +30% food income.",
    "greyjoy":        "Reavers: can RAID across the sea; +15% strength attacking from the sea.",
    "martell":        "Unbowed: +40% defense in Dorne.",
    "arryn":          "Moon Door: The Eyrie's 2.2x defense (regional).",
    "tully":          "River supply: +20% food income.",
    "nights_watch":   "Sworn brothers: cannot attack house-held regions; +40 free recruits per turn.",
    "free_folk":      "No gold economy: recruit with food; can RAID.",
    "white_walkers":  "Army of the dead: no upkeep, grows in winter, raises fallen enemies; cannot attack outside winter; no diplomacy.",
    "dothraki":       "Horse lords: +30% attacking open land (defense < 1.5); need ships (or allies' ships) to cross the sea; can RAID.",
    "iron_bank":      "Lender: can LEND/FUND gold, cannot attack.",
    "golden_company": "Sellswords: troops can be HIRED by contract.",
}

MARRIED = [("stark", "tully"), ("arryn", "tully"), ("baratheon", "lannister"), ("targaryen", "dothraki")]
ALLIED = MARRIED + [("stark", "arryn"), ("stark", "nights_watch")]

LORE_RELATIONS = {
    ("stark", "baratheon"): 40, ("stark", "lannister"): -25, ("stark", "greyjoy"): -15, ("stark", "nights_watch"): 40,
    ("stark", "targaryen"): -20, ("stark", "free_folk"): -30, ("stark", "tully"): 50, ("stark", "arryn"): 30,
    ("baratheon", "lannister"): 20, ("baratheon", "targaryen"): -80, ("baratheon", "tyrell"): 10,
    ("lannister", "targaryen"): -50, ("lannister", "martell"): -45, ("lannister", "tully"): -20, ("lannister", "iron_bank"): 10,
    ("targaryen", "martell"): 30, ("targaryen", "dothraki"): 60, ("targaryen", "greyjoy"): -10,
    ("tyrell", "lannister"): 0, ("tyrell", "martell"): -10, ("arryn", "tully"): 40,
    ("nights_watch", "free_folk"): -50, ("greyjoy", "tully"): -20, ("greyjoy", "tyrell"): -15,
}
for _f in FACTIONS:
    if _f != "white_walkers":
        LORE_RELATIONS[(_f, "white_walkers")] = -100


def adjacency():
    adj = {r: {} for r in REGIONS}
    for a, b in LAND_EDGES:
        adj[a][b] = "land"; adj[b][a] = "land"
    for a, b in SEA_EDGES:
        adj[a][b] = "sea"; adj[b][a] = "sea"
    return adj
