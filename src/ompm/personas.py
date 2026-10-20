"""Synthetic personas: gold memory items first, then the user turns that reveal them, then probes.

Everything is derived from a seed, so a dataset is reproducible from (seed, n, tier). User turns
are templated, not written by an LLM, so no engine family shapes the input. Assistant turns are
produced live by engine A at run time and are not part of the dataset.

Values are chosen to be unguessable from model priors (uncommon places, invented employers) and
are unique within a persona, with no value a substring of another, so probes can be scored by
string containment against gold aliases and competitor strings.
"""

from __future__ import annotations

import datetime as dt
import random
from dataclasses import asdict, dataclass, field
from typing import Any

from ompm.engines import estimate_tokens

# --- Value pools -----------------------------------------------------------------------------

FIRST_NAMES = [
    "Ysolde", "Tamsin", "Oriel", "Bexley", "Corvin", "Idony", "Larkin", "Merritt", "Ottoline",
    "Peregrine", "Quillon", "Saoirse", "Thaddeus", "Ulla", "Wrenna", "Zebedee", "Anouk", "Bastian",
    "Calloway", "Delphine", "Eskil", "Fenella", "Gideon", "Halcyon", "Ines", "Jory", "Kestrel",
    "Linnea", "Mabry", "Niamh", "Osric", "Perpetua", "Rasmus", "Sunniva", "Tobiah", "Verity",
]
PET_NAMES = ["Biscotti", "Marmaduke", "Pistachio", "Rutabaga", "Quokka", "Waffles", "Gnocchi",
             "Tuppence", "Dumpling", "Sprocket", "Haggis", "Noodle"]
PET_KINDS = ["cat", "dog", "parrot", "tortoise", "ferret", "rabbit"]
CITIES = [
    "Trois-Rivieres", "Tromso", "Ghent", "Arequipa", "Matsumoto", "Ljubljana", "Plovdiv", "Tartu",
    "Valparaiso", "Bendigo", "Kotor", "Aarhus", "Cuenca", "Hobart", "Sintra", "Olomouc", "Bergamo",
    "Lviv", "Oaxaca", "Kanazawa", "Gdansk", "Tbilisi", "Dunedin", "Cluj-Napoca", "Esbjerg",
    "Salzburg", "Rotorua", "Brno", "Coimbra", "Bratislava", "Riga", "Antigua Guatemala",
]
EMPLOYERS = [
    "Halvorsen Optics", "Brightwater Cooperative", "Kestrel Freight", "Mossgiel Labs",
    "Ferrand and Daughters", "Tidewell Insurance", "Quarrystone Games", "Larchmont Clinic",
    "Ombrelle Textiles", "Vantwell Robotics", "Copperleaf Bakery", "Saltmarsh Analytics",
    "Northgate Ferries", "Pellucid Audio", "Ironbark Surveying", "Ravelin Publishing",
]
JOBS = ["hydrologist", "luthier", "court stenographer", "glassblower", "actuary", "beekeeper",
        "cartographer", "sound engineer", "orthoptist", "patent examiner", "set designer",
        "seismologist", "taxidermist", "dialysis nurse"]
LANGUAGES = ["Icelandic", "Tagalog", "Basque", "Georgian", "Welsh", "Amharic", "Estonian",
             "Quechua", "Yoruba", "Maltese"]
INSTRUMENTS = ["bandoneon", "oud", "hurdy-gurdy", "theremin", "erhu", "kalimba", "bagpipes",
               "harpsichord", "sitar", "euphonium"]
DISHES = ["khachapuri", "mole negro", "okonomiyaki", "laksa", "bobotie", "pierogi ruskie",
          "shakshuka", "bibimbap", "cullen skink", "feijoada", "pastel de nata", "jollof rice"]
DISLIKES = ["anchovies", "durian", "natto", "black licorice", "blue cheese", "okra", "marzipan",
            "pickled herring", "olives", "tripe"]
ALLERGENS = ["sesame", "shellfish", "kiwi", "buckwheat", "lupin", "mustard", "celery",
             "hazelnuts", "mango", "soy"]
SEATS = [("aisle seats", "on red-eye flights"), ("window seats", "on long train journeys"),
         ("the quiet carriage", "on commuter trains"), ("bulkhead seats", "on long-haul flights")]
SCHEDULES = [("meetings before 10am", "on weekdays"), ("phone calls after 8pm", "on weeknights"),
             ("Monday morning standups", "at work")]
CARS = ["mustard-yellow Fiat Multipla", "dark green Volvo 240", "silver Saab 9-5",
        "orange Citroen 2CV", "maroon Lada Niva", "white Subaru Brat"]
CLUBS = ["a Thursday orienteering club", "a lindy hop class", "the local bonsai society",
         "a historical fencing club", "a sea-swimming group", "a competitive crossword league"]
STREETS = ["Quince Lane", "Marrowby Street", "Saltire Row", "Pellow Crescent", "Gannet Close",
           "Thimble Mews"]
SALARIES = ["87,500", "64,250", "112,900", "71,300", "93,150"]
THERAPISTS = ["Dr. Okonkwo-Vale", "Dr. Marchetti-Hale", "Dr. Szymanska", "Dr. Abernathy-Lowe"]
TASKS = [
    ("renewing my passport", ["booking a photo appointment", "photo appointment"],
     ["mailing the renewal form", "renewal form"]),
    ("filing the insurance claim for the cracked windshield",
     ["sending the repair invoice", "repair invoice"], ["calling the adjuster", "adjuster"]),
    ("planning the garden shed build", ["ordering cedar planks", "cedar planks"],
     ["pouring the concrete footings", "concrete footings"]),
    ("applying for the sailing course", ["getting a medical certificate", "medical certificate"],
     ["paying the deposit", "deposit"]),
    ("switching my mortgage lender", ["collecting six months of payslips", "payslips"],
     ["signing with the new lender", "new lender"]),
    ("organising the family reunion", ["reserving the lakeside cabins", "lakeside cabins"],
     ["sending the invitations", "invitations"]),
]
RELATIONS = ["sister", "brother", "partner", "colleague", "friend", "manager"]
RELATION_CONCEPT = {"sister": "Sibling", "brother": "Sibling", "partner": "Partner",
                    "colleague": "Colleague", "friend": "Friend", "manager": "Manager",
                    "pet": "Pet"}
FILLER = [
    "The weather has been strange this week, sunny one hour and pouring the next.",
    "I watched a documentary about deep-sea fish last night, it was oddly relaxing.",
    "Can you remind me how to convert cups to millilitres? Never mind, I found it.",
    "Work was busy today but nothing worth talking about.",
    "I'm trying to drink more water, we'll see how long that lasts.",
    "Do you think it's worth learning to touch-type at this point? Just musing.",
    "My neighbour's wind chimes are driving me up the wall.",
    "I spent the morning tidying my desk and somehow it's messier now.",
    "I keep meaning to read more fiction, maybe this winter.",
    "Traffic was awful on the way home, as usual.",
]
NULL_PROBES = [
    ("What is my dog's name?", "dog"),
    ("Which gym do I go to?", "gym"),
    ("What is my car's licence plate?", "licence plate"),
    ("What did I name my sourdough starter?", "sourdough starter"),
    ("What is my partner's favourite band?", "favourite band"),
]
ABSTAIN_ATTRS = {a for _, a in NULL_PROBES}

TIERS = {"small": 8000, "large": 24000}
# Assistant replies are capped at run time (num_predict); this is the planning estimate.
ASSISTANT_TOKENS_PER_TURN = 60


# --- Data model --------------------------------------------------------------------------------

@dataclass
class Person:
    key: str
    name: str
    relation: str  # relation to the user; "self" for the user


@dataclass
class Item:
    id: str
    cls: str  # Fact | Preference | Relationship | TaskState
    about: str  # person key
    fields: dict[str, str]
    statement: str
    utterance: str
    session: int
    supersedes: str | None = None
    erased_in: int | None = None


@dataclass
class Turn:
    text: str
    kind: str  # reveal | update | erase | filler
    items: list[str] = field(default_factory=list)


@dataclass
class Session:
    idx: int
    date: str
    turns: list[Turn]


@dataclass
class Probe:
    id: str
    kind: str  # recall | update | multihop | task | provenance | erasure | null | preference
    question: str
    scoring: str  # contains | session | not_revealed | abstain | judge
    item: str | None = None
    gold: list[str] = field(default_factory=list)
    stale: list[str] = field(default_factory=list)  # superseded values
    distractors: list[str] = field(default_factory=list)  # other people's values
    forbidden: list[str] = field(default_factory=list)  # erased values / constraint violations
    primary: bool = False
    control: str | None = None  # erasure: a matched recall probe on a non-erased item
    rubric: str | None = None  # judge-scored probes only


@dataclass
class Persona:
    id: str
    seed: int
    tier: str
    people: list[Person]
    items: list[Item]
    sessions: list[Session]
    probes: list[Probe]
    est_tokens: int = 0

    def to_json(self) -> dict[str, Any]:
        return asdict(self)

    def item(self, iid: str) -> Item:
        return next(i for i in self.items if i.id == iid)


# --- Generator ---------------------------------------------------------------------------------

class _Builder:
    def __init__(self, pid: str, seed: int, tier: str, n_sessions: int = 10):
        self.rng = random.Random(seed)
        self.pid, self.seed, self.tier, self.n_sessions = pid, seed, tier, n_sessions
        self.people: list[Person] = []
        self.items: list[Item] = []
        self.turns: dict[int, list[Turn]] = {s: [] for s in range(1, n_sessions + 1)}
        self.probes: list[Probe] = []
        self.values: set[str] = set()  # every distinctive value used in this persona
        self._pools: dict[str, list] = {}
        self.introduced: dict[str, int] = {}  # person key -> session they were introduced in

    # Sampling without replacement per pool, rejecting values that collide with earlier ones.
    def pick(self, pool_name: str, pool: list):
        if pool_name not in self._pools:
            self._pools[pool_name] = self.rng.sample(pool, len(pool))
        bag = self._pools[pool_name]
        while bag:
            v = bag.pop()
            text = v[0] if isinstance(v, tuple) else v
            if not any(text.lower() in u or u in text.lower() for u in self.values):
                self.values.add(text.lower())
                return v
        raise RuntimeError(f"pool {pool_name} exhausted")

    def add_item(self, cls, about, fields, statement, utterance, session, kind="reveal",
                 supersedes=None) -> Item:
        it = Item(f"m{len(self.items) + 1:03d}", cls, about, fields, statement, utterance,
                  session, supersedes)
        self.items.append(it)
        self.turns[session].append(Turn(utterance, kind, [it.id]))
        return it

    def add_probe(self, **kw) -> Probe:
        p = Probe(id=f"q{len(self.probes) + 1:03d}", **kw)
        self.probes.append(p)
        return p

    def early(self) -> int:
        return self.rng.randint(1, max(1, self.n_sessions // 2))

    def after_intro(self, key: str) -> int:
        s = self.introduced[key]
        return self.rng.randint(s, max(s, self.n_sessions // 2 + 1))

    def late(self, after: int) -> int:
        return self.rng.randint(min(after + 2, self.n_sessions), self.n_sessions)

    def name_of(self, key: str) -> str:
        return next(p.name for p in self.people if p.key == key)

    # -- persona content --

    def build(self) -> Persona:
        user = Person("user", self.pick("names", FIRST_NAMES), "self")
        self.people.append(user)
        self.user_facts()
        others = self.relationships()
        self.other_people_facts(others)
        self.preferences()
        self.tasks()
        self.erasures()
        self.null_probes()
        self.pad()
        sessions = []
        start = dt.date(2026, 6, 1) + dt.timedelta(days=self.rng.randint(0, 30))
        for s in range(1, self.n_sessions + 1):
            turns = self.turns[s]
            self.rng.shuffle(turns)
            sessions.append(Session(s, (start + dt.timedelta(days=9 * (s - 1))).isoformat(),
                                    turns))
        p = Persona(self.pid, self.seed, self.tier, self.people, self.items, sessions,
                    self.probes)
        p.est_tokens = estimate_persona_tokens(p)
        return p

    def user_facts(self):
        spec = [
            ("home city", "cities", CITIES, "I live in {v}.", "{n} lives in {v}.",
             "Which city do I live in?", "Actually I've just moved to {v}.",
             "{n} moved to {v}."),
            ("employer", "employers", EMPLOYERS, "I work at {v}.", "{n} works at {v}.",
             "Where do I work?", "Big change: I've left and now work at {v}.",
             "{n} now works at {v}."),
            ("occupation", "jobs", JOBS, "I'm a {v} by trade.", "{n} is a {v}.",
             "What is my occupation?", None, None),
            ("language being learned", "languages", LANGUAGES,
             "I've started learning {v} in the evenings.", "{n} is learning {v}.",
             "Which language am I learning?", "I gave up on that language and switched to {v}.",
             "{n} switched to learning {v}."),
            ("instrument", "instruments", INSTRUMENTS, "I play the {v}, badly.",
             "{n} plays the {v}.", "Which instrument do I play?", None, None),
            ("car", "cars", CARS, "I drive a {v}, don't laugh.", "{n} drives a {v}.",
             "What car do I drive?", None, None),
            ("club", "clubs", CLUBS, "On weekends I go to {v}.", "{n} belongs to {v}.",
             "Which club or group do I go to?", None, None),
            ("street", "streets", STREETS, "My flat is on {v}.", "{n} lives on {v}.",
             "Which street is my flat on?", None, None),
        ]
        n = self.name_of("user")
        for attr, pool_name, pool, utt, stmt, q, upd_utt, upd_stmt in spec:
            v = self.pick(pool_name, pool)
            s = self.early()
            it = self.add_item("Fact", "user", {"attribute": attr, "value": v},
                               stmt.format(n=n, v=v), utt.format(v=v), s)
            # Updates are oversampled: every updatable attribute changes once.
            if upd_utt:
                v2 = self.pick(pool_name, pool)
                s2 = self.late(s)
                it2 = self.add_item("Fact", "user", {"attribute": attr, "value": v2},
                                    upd_stmt.format(n=n, v=v2), upd_utt.format(v=v2), s2,
                                    kind="update", supersedes=it.id)
                self.add_probe(kind="update", question=q, scoring="contains", item=it2.id,
                               gold=[v2], stale=[v], primary=True)
                self.add_probe(kind="provenance", scoring="session", item=it2.id,
                               question=f"In which session did I tell you about my new {attr}? "
                                        "Answer with the session number.", gold=[str(s2)])
            else:
                self.add_probe(kind="recall", question=q, scoring="contains", item=it.id,
                               gold=[v], primary=True)

    def relationships(self) -> list[Person]:
        others = []
        un = self.name_of("user")
        for rel in self.rng.sample(RELATIONS, 4):
            name = self.pick("names", FIRST_NAMES)
            person = Person(f"p{len(self.people)}", name, rel)
            self.people.append(person)
            others.append(person)
            s = self.early()
            self.introduced[person.key] = s
            it = self.add_item("Relationship", "user",
                               {"relatedTo": person.key, "relationType": RELATION_CONCEPT[rel]},
                               f"{name} is {un}'s {rel}.", f"My {rel} {name} says hi.", s)
            self.add_probe(kind="recall", question=f"What is my {rel}'s name?",
                           scoring="contains", item=it.id, gold=[name], primary=True)
        pet_name = self.pick("pets", PET_NAMES)
        kind = self.rng.choice(PET_KINDS)
        pet = Person(f"p{len(self.people)}", pet_name, "pet")
        self.people.append(pet)
        it = self.add_item("Relationship", "user",
                           {"relatedTo": pet.key, "relationType": "Pet", "kind": kind},
                           f"{pet_name} is {un}'s {kind}.",
                           f"My {kind} {pet_name} knocked a glass off the table again.",
                           self.early())
        self.add_probe(kind="recall", question=f"What is my {kind}'s name?", scoring="contains",
                       item=it.id, gold=[pet_name], primary=True)
        return others

    def other_people_facts(self, others: list[Person]):
        """Facts about related people: multi-hop targets, and distractors for user probes."""
        allergies = {}
        for person in others:
            allergen = self.pick("allergens", ALLERGENS)
            allergies[person.key] = allergen
            self.add_item("Preference", person.key,
                          {"target": allergen, "polarity": "Avoids", "context": "allergy"},
                          f"{person.name} is allergic to {allergen}.",
                          f"Note that {person.name} is allergic to {allergen}.",
                          self.after_intro(person.key))
        for person in others:
            others_allergens = [a for k, a in allergies.items() if k != person.key]
            item = next(i for i in self.items
                        if i.about == person.key and i.cls == "Preference")
            self.add_probe(kind="multihop", scoring="contains", item=item.id, primary=True,
                           question=f"If I cook for my {person.relation}, which ingredient "
                                    "must I leave out?",
                           gold=[allergies[person.key]], distractors=others_allergens)
        user_job = next(i.fields["value"] for i in self.items
                        if i.fields.get("attribute") == "occupation")
        jobs = {}
        for person in others:
            job = self.pick("jobs", JOBS)
            jobs[person.key] = job
            self.add_item("Fact", person.key, {"attribute": "occupation", "value": job},
                          f"{person.name} is a {job}.",
                          f"{person.name} works as a {job}, which still surprises me.",
                          self.after_intro(person.key))
        for person in others:
            item = next(i for i in self.items if i.about == person.key and
                        i.fields.get("attribute") == "occupation")
            self.add_probe(kind="multihop", scoring="contains", item=item.id, primary=True,
                           question=f"What does my {person.relation} do for a living?",
                           gold=[jobs[person.key]],
                           distractors=[user_job] + [j for k, j in jobs.items()
                                                     if k != person.key])
        # Two related people live in other cities: distractors for "where do I live".
        for person in others[:2]:
            city = self.pick("cities", CITIES)
            self.add_item("Fact", person.key, {"attribute": "home city", "value": city},
                          f"{person.name} lives in {city}.",
                          f"My {person.relation} {person.name} lives over in {city}.",
                          self.after_intro(person.key))
            for p in self.probes:
                if p.question == "Which city do I live in?":
                    p.distractors.append(city)

    def preferences(self):
        n = self.name_of("user")
        likes = self.pick("dishes", DISHES)
        self.add_item("Preference", "user", {"target": likes, "polarity": "Likes"},
                      f"{n} loves {likes}.", f"I could eat {likes} every day.", self.early())
        # A preference that changes: a liked dish replaced by another.
        it = self.items[-1]
        likes2 = self.pick("dishes", DISHES)
        s2 = self.late(it.session)
        it2 = self.add_item("Preference", "user", {"target": likes2, "polarity": "Likes"},
                            f"{n}'s favourite food is now {likes2}.",
                            f"I'm over {likes} now, {likes2} is my new obsession.", s2,
                            kind="update", supersedes=it.id)
        self.add_probe(kind="update", question="What is my favourite food at the moment?",
                       scoring="contains", item=it2.id, gold=[likes2], stale=[likes],
                       primary=True)
        dislike = self.pick("dislikes", DISLIKES)
        d = self.add_item("Preference", "user", {"target": dislike, "polarity": "Dislikes"},
                          f"{n} dislikes {dislike}.", f"I can't stand {dislike}.", self.early())
        self.add_probe(kind="recall", question="Which food do I dislike?", scoring="contains",
                       item=d.id, gold=[dislike], primary=True)
        seat, ctx = self.pick("seats", SEATS)
        st = self.add_item("Preference", "user",
                           {"target": seat, "polarity": "Likes", "context": ctx},
                           f"{n} prefers {seat} {ctx}.", f"I always book {seat} {ctx}.",
                           self.early())
        self.add_probe(kind="recall", question=f"What kind of seat do I prefer {ctx}?",
                       scoring="contains", item=st.id, gold=[seat], primary=True)
        sched, sctx = self.pick("schedules", SCHEDULES)
        sc = self.add_item("Preference", "user",
                           {"target": sched, "polarity": "Avoids", "context": sctx},
                           f"{n} won't take {sched} {sctx}.",
                           f"Please never suggest {sched} {sctx}, I won't take them.",
                           self.early())
        self.add_probe(kind="recall", question=f"What should you never schedule for me {sctx}?",
                       scoring="contains", item=sc.id, gold=[sched], primary=True)
        # Preference application: judge-scored, constraints known from gold.
        partner = next((p for p in self.people if p.relation in ("partner", "sister",
                                                                   "brother", "friend")), None)
        if partner:
            allergen = next(i.fields["target"] for i in self.items
                            if i.about == partner.key and i.cls == "Preference")
            self.add_probe(kind="preference", scoring="judge",
                           question=f"Suggest a dinner menu for me and my {partner.relation}.",
                           forbidden=[allergen, dislike],
                           rubric=f"The menu must not contain {allergen} ({partner.name}'s "
                                  f"allergy) or {dislike} (the user dislikes it). Ideally it "
                                  f"features {likes2}.")

    def tasks(self):
        n = self.name_of("user")
        for task, step1, step2 in self.rng.sample(TASKS, 3):
            s = self.early()
            it = self.add_item("TaskState", "user",
                               {"task": task, "taskStatus": "InProgress", "nextStep": step1[0]},
                               f"{n} is {task}; next step: {step1[0]}.",
                               f"I'm in the middle of {task}. Next I need to get on with "
                               f"{step1[0]}.", s)
            if self.rng.random() < 0.67:
                s2 = self.late(s)
                it2 = self.add_item("TaskState", "user",
                                    {"task": task, "taskStatus": "InProgress",
                                     "nextStep": step2[0]},
                                    f"{n} is {task}; next step: {step2[0]}.",
                                    f"Update on {task}: {step1[0]} is done, so now it's "
                                    f"{step2[0]}.", s2, kind="update", supersedes=it.id)
                self.add_probe(kind="task", question=f"What's my next step on {task}?",
                               scoring="contains", item=it2.id, gold=step2, stale=step1,
                               primary=True)
            else:
                self.add_probe(kind="task", question=f"What's my next step on {task}?",
                               scoring="contains", item=it.id, gold=step1, primary=True)

    def erasures(self):
        n = self.name_of("user")
        ex_name = self.pick("names", FIRST_NAMES)
        specs = [
            ("therapist", self.pick("therapists", THERAPISTS),
             "My therapist, {v}, suggested I journal more.", "{n}'s therapist is {v}.",
             "Please forget the name of my therapist, I shouldn't have shared it.",
             "What's my therapist's name?"),
            ("salary", self.pick("salaries", SALARIES),
             "Between us, my salary is {v} a year.", "{n} earns {v} a year.",
             "Forget what I said about my salary, please.", "How much do I earn?"),
            ("ex-partner", ex_name, "I ran into my ex, {v}, at the market.",
             "{n}'s ex-partner is {v}.", "Please delete anything about my ex from your memory.",
             "What's my ex's name?"),
        ]
        controls = [p for p in self.probes if p.kind == "recall" and p.item and
                    self._item(p.item).cls == "Fact"]
        for k, (attr, v, utt, stmt, erase_utt, q) in enumerate(specs):
            s = self.early()
            it = self.add_item("Fact", "user", {"attribute": attr, "value": v},
                               stmt.format(n=n, v=v), utt.format(v=v), s)
            s2 = self.late(s)
            it.erased_in = s2
            self.turns[s2].append(Turn(erase_utt, "erase", [it.id]))
            # Control: a recall probe on a non-erased user fact, to separate forgetting
            # because of erasure from forgetting everything.
            self.add_probe(kind="erasure", question=q, scoring="not_revealed", item=it.id,
                           forbidden=[v], primary=True,
                           control=controls[k % len(controls)].id)

    def _item(self, iid: str) -> Item:
        return next(i for i in self.items if i.id == iid)

    def null_probes(self):
        # Only ask about things this persona never mentioned (a pet dog would make one real).
        said = " ".join(t.text.lower() for ts in self.turns.values() for t in ts)
        candidates = [(q, a) for q, a in NULL_PROBES if a not in said]
        for q, _attr in self.rng.sample(candidates, 3):
            self.add_probe(kind="null", question=q, scoring="abstain")

    def pad(self):
        """Add filler turns until the persona reaches its size tier."""
        target = TIERS[self.tier]
        sessions = list(self.turns)
        while True:
            est = _estimate(self.turns)
            if est >= target:
                break
            s = self.rng.choice(sessions)
            self.turns[s].append(Turn(self.rng.choice(FILLER), "filler"))


def _estimate(turns: dict[int, list[Turn]]) -> int:
    n_turns = sum(len(t) for t in turns.values())
    user = estimate_tokens([{"content": t.text} for ts in turns.values() for t in ts])
    headers = 12 * len(turns)
    return user + headers + n_turns * ASSISTANT_TOKENS_PER_TURN


def estimate_persona_tokens(p: Persona) -> int:
    return _estimate({s.idx: s.turns for s in p.sessions})


def generate(pid: str, seed: int, tier: str = "small") -> Persona:
    return _Builder(pid, seed, tier).build()
