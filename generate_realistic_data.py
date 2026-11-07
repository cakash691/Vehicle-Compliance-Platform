#!/usr/bin/env python3
"""
generate_realistic_data.py -- the source data for the Vehicle Compliance Platform.

Writes CSVs for the four independent source systems:
  sources/registrations.csv     RTO / VAHAN-style registry
  sources/policies.csv          insurer feed (IIB-style), full policy history since 2023
  sources/capture_log.csv       ANPR reads: real NHAI toll plazas + city ITMS cameras
  sources/theft_shredding.csv   police theft FIRs + RVSF scrapping certificates
plus daily/<YYYY-MM-DD>/*.csv  -- three nightly drops after the base cut-off,
and calibration_report.md       -- the simulated data measured against official figures.

Individual records are simulated (real per-vehicle records are not public), but every
distribution is calibrated to a published figure (see DATA_SOURCES.md) and the reference
data -- RTO codes, NHAI toll plazas -- is real. Seeded: same --seed and --vehicles give
byte-identical output. Python 3.8+, standard library only.

Usage:
  python3 generate_realistic_data.py                      # 100,000 vehicles (default)
  python3 generate_realistic_data.py --vehicles 300000    # bigger
  python3 generate_realistic_data.py --vehicles 20000 --report-only   # quick calibration check
"""
import argparse, bisect, csv, math, os, random, sys, zlib
from collections import Counter, defaultdict
from datetime import date, datetime, timedelta

HERE = os.path.dirname(os.path.abspath(__file__))
ap = argparse.ArgumentParser(description="Generate the CSV files of the four source systems")
ap.add_argument("--vehicles", type=int, default=100_000, help="registry size (default 100000)")
ap.add_argument("--seed", type=int, default=42)
ap.add_argument("--out", default=HERE, help="output folder (default: this script's folder)")
ap.add_argument("--report-only", action="store_true", help="only print the calibration report")
args = ap.parse_args()
R = random.Random(args.seed)

# ----------------------------------------------------------------------------------------
# Timeline
# ----------------------------------------------------------------------------------------
REG_START         = date(2008, 1, 1)                 # oldest registration in the registry
BASE_CUTOFF       = datetime(2026, 11, 3, 23, 59, 59)  # base load = everything ingested up to here
DROP_DAYS         = [date(2026, 11, 4), date(2026, 11, 5), date(2026, 11, 6)]
END_DT            = datetime(2026, 11, 6, 23, 59, 59)
END               = END_DT.date()
CAP_START         = date(2025, 11, 7)                # 365 days of ANPR captures
POLICY_FEED_FROM  = date(2023, 1, 1)                 # feed holds every policy in force on/after this
THEFT_FEED_FROM   = date(2019, 1, 1)
LT_TP_FROM        = date(2018, 9, 1)                 # SC order: 3-yr TP new cars, 5-yr TP new 2W
BH_FROM           = date(2021, 9, 15)                # Bharat series
SCRAP_FROM        = date(2022, 4, 1)                 # RVSF scrappage policy in force
GOVT_15Y_FROM     = date(2023, 4, 1)                 # CMVR (First Amendment) Rules 2023
BHARTI_AXA_LAST   = date(2021, 9, 7)                 # merged into ICICI Lombard on 8-Sep-2021
INDUSIND_FROM     = date(2025, 9, 22)                # Reliance General renamed IndusInd General
TS_FROM, TG_FROM  = date(2014, 6, 2), date(2024, 3, 15)
OD_FROM, LA_FROM  = date(2012, 9, 1), date(2019, 10, 31)

# ----------------------------------------------------------------------------------------
# Small helpers
# ----------------------------------------------------------------------------------------
def read_ref(name):
    with open(os.path.join(HERE, "ref", name), newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))

class WChoice:
    """Weighted random choice with O(log n) picks."""
    __slots__ = ("items", "cum", "total")
    def __init__(self, pairs):
        self.items, self.cum, acc = [], [], 0.0
        for item, w in pairs:
            if w > 0:
                acc += w; self.items.append(item); self.cum.append(acc)
        self.total = acc
    def __call__(self):
        return self.items[min(len(self.items) - 1, bisect.bisect_right(self.cum, R.random() * self.total))]

def wpick(pairs):
    tot = sum(w for _, w in pairs); x = R.random() * tot
    for item, w in pairs:
        x -= w
        if x < 0: return item
    return pairs[-1][0]

def poisson(lam):
    if lam <= 0: return 0
    if lam < 30:
        L, k, p = math.exp(-lam), 0, 1.0
        while True:
            p *= R.random()
            if p <= L: return k
            k += 1
    return max(0, int(round(R.gauss(lam, math.sqrt(lam)))))

def add_years(d, n):
    try: return d.replace(year=d.year + n)
    except ValueError: return d.replace(year=d.year + n, day=28)

def days(n): return timedelta(days=n)
def exp_after(a, rate_per_year, limit):
    """Next event of a Poisson process (rate per year) starting at date a; None if it falls after `limit`."""
    if rate_per_year <= 0 or a >= limit: return None
    dd = R.expovariate(rate_per_year) * 365.25
    return None if dd > (limit - a).days else a + days(int(dd))
def rand_date(a, b): return a + days(R.randint(0, max(0, (b - a).days)))
def iso(d): return d.isoformat() if d else ""
def isodt(x): return x.strftime("%Y-%m-%d %H:%M:%S") if x else ""
def stable_hash(s): return zlib.crc32(s.encode())

LETTERS = "ABCDEFGHJKLMNPQRSTUVWXYZ"       # Indian series letters skip I and O
VIN_CHARS = "ABCDEFGHJKLMNPRSTUVWXYZ0123456789"
VIN_YEAR = {2007: "7", 2008: "8", 2009: "9", 2010: "A", 2011: "B", 2012: "C", 2013: "D", 2014: "E", 2015: "F",
            2016: "G", 2017: "H", 2018: "J", 2019: "K", 2020: "L", 2021: "M", 2022: "N", 2023: "P",
            2024: "R", 2025: "S", 2026: "T", 2027: "V"}

# ----------------------------------------------------------------------------------------
# Reference data (real): states, RTO offices, NHAI toll plazas; synthetic city camera sites
# ----------------------------------------------------------------------------------------
STATES = {s["state_key"]: s for s in read_ref("states.csv")}
_theft_norm = sum(float(s["vehicle_share"]) * float(s["theft_rate_multiplier"]) for s in STATES.values())
STATE_PICK = WChoice((k, float(s["vehicle_share"])) for k, s in STATES.items())

OFFICES = read_ref("rto_offices.csv")
for o in OFFICES:
    o["rto_number"] = int(o["rto_number"])
    o["vf"] = date.fromisoformat(o["valid_from"]) if o["valid_from"] else date(1900, 1, 1)
    o["vt"] = date.fromisoformat(o["valid_to"]) if o["valid_to"] else date(2100, 1, 1)
    o["comm"] = o["commercial_only"] == "1"
    o["days_per_series"] = 20 + stable_hash(o["rto_code"] + o["valid_from"]) % 140   # series exhaustion speed
    o["series_offset"] = stable_hash(o["rto_code"]) % 90
BIG = ("Mumbai", "Pune", "Bangalore", "Chennai", "Hyderabad", "Khairatabad", "Secunderabad", "Malakpet",
       "Mehdipatnam", "Bahadurpura", "Delhi", "Kolkata", "Ahmedabad", "Surat", "Jaipur", "Lucknow", "Kanpur",
       "Nagpur", "Indore", "Bhopal", "Patna", "Thane", "Gurgaon", "NOIDA", "Ghaziabad", "Vadodara",
       "Ludhiana", "Coimbatore", "Madurai", "Eranakulam", "Thiruvananthapuram City", "Visakhapatnam",
       "Bejawada", "Bhubaneswar", "Guwahati", "Kamrup", "Raipur", "Ranchi", "Dehradun", "Chandigarh",
       "Srinagar", "Jammu", "Agra", "Varanasi", "Meerut", "Rajkot", "Nashik", "Faridabad", "Kalyan")
OFFICES_BY_STATE = defaultdict(list)
for o in OFFICES:
    OFFICES_BY_STATE[o["state_key"]].append(o)
_office_cache = {}
def pick_office(state, d, transport):
    era = (d >= OD_FROM, d >= TS_FROM, d >= LA_FROM, d >= TG_FROM)
    key = (state, era, transport)
    wc = _office_cache.get(key)
    if wc is None:
        pairs = []
        for o in OFFICES_BY_STATE[state]:
            if not (o["vf"] <= d <= o["vt"]): continue
            if o["comm"] and not transport: continue
            w = 4.0 if any(b in o["rto_name"] for b in BIG) else 1.0
            if o["comm"]: w *= 3.0
            pairs.append((o, w))
        wc = _office_cache[key] = WChoice(pairs)
    return wc()

TOLLS = read_ref("toll_plazas.csv")
for t in TOLLS:
    tpd = t["traffic_per_day"]
    t["w"] = math.sqrt(int(tpd) / 10000.0) if tpd.isdigit() and int(tpd) > 0 else 1.0
    nm = t["plaza_name"]
    t["location"] = nm if ("toll" in nm.lower() or "plaza" in nm.lower()) else f"{nm} Toll Plaza"
TOLLS_BY_STATE = defaultdict(list)
for t in TOLLS: TOLLS_BY_STATE[t["state_key"]].append(t)
TOLL_NATIONAL = WChoice((t, t["w"]) for t in TOLLS)
TOLL_STATE = {k: WChoice((t, t["w"]) for t in v) for k, v in TOLLS_BY_STATE.items()}
def _km(a, b):
    la1, lo1, la2, lo2 = map(math.radians, (a["lat"], a["lon"], b["lat"], b["lon"]))
    h = math.sin((la2 - la1) / 2) ** 2 + math.cos(la1) * math.cos(la2) * math.sin((lo2 - lo1) / 2) ** 2
    return 12742 * math.asin(math.sqrt(h))
for t in TOLLS: t["lat"], t["lon"] = float(t["latitude"]), float(t["longitude"])
NEAR = {t["plaza_id"]: sorted(((_km(t, u), u) for u in TOLLS if u is not t), key=lambda x: x[0])[:8] for t in TOLLS}
NEIGHBOURS = {"DL": ["HR", "UP"], "CH": ["PB", "HR"], "GA": ["MH", "KA"], "PY": ["TN"], "KL": ["TN", "KA"],
              "HP": ["PB", "HR"], "UK": ["UP"], "JK": ["PB"], "LA": ["JK"], "SK": ["WB"], "DD": ["GJ", "MH"],
              "TS": ["AP", "MH", "KA"], "AP": ["TS", "TN", "KA"], "HR": ["RJ", "UP", "PB"], "UP": ["MP", "RJ", "BR"],
              "MH": ["GJ", "KA", "MP"], "KA": ["TN", "MH", "AP"], "TN": ["KA", "AP"], "GJ": ["RJ", "MH"],
              "WB": ["JH", "OD", "BR"], "BR": ["UP", "JH"], "JH": ["WB", "BR", "OD"], "OD": ["AP", "WB", "CG"],
              "CG": ["MP", "OD"], "MP": ["RJ", "UP", "MH"], "RJ": ["GJ", "HR", "MP"], "PB": ["HR", "RJ"],
              "AS": ["ML", "WB"], "ML": ["AS"], "AR": ["AS"], "NL": ["AS"], "MN": ["AS"], "MZ": ["AS"], "TR": ["AS"]}

CAMS = read_ref("city_cameras.csv")
CAMS_BY_CITY = defaultdict(list)
CITY_INFO = {}
for c in CAMS:
    CAMS_BY_CITY[c["city"]].append(c)
    CITY_INFO[c["city"]] = (c["state_key"], float(c["city_weight"]))
CITY_BY_STATE = defaultdict(list)
for city, (sk, w) in CITY_INFO.items(): CITY_BY_STATE[sk].append((city, w))
CITY_PICK = {sk: WChoice(v) for sk, v in CITY_BY_STATE.items()}
ALL_CITY_PICK = WChoice((city, w) for city, (sk, w) in CITY_INFO.items())

# ----------------------------------------------------------------------------------------
# Fleet composition (MoRTH, as on 31-03-2020): 2W 74.7%, cars/jeeps/taxis 13.4%, goods 4.4%,
# buses 0.7%, others 6.9%  -- split into the classes below, then nudged per state.
# ----------------------------------------------------------------------------------------
CLASSES = ["2W", "CAR", "TAXI", "LCV", "TRUCK", "BUS", "3W_P", "3W_G", "ERICK", "TRACTOR"]
BASE_MIX = {"2W": .745, "CAR": .123, "TAXI": .011, "LCV": .025, "TRUCK": .020, "BUS": .007,
            "3W_P": .031, "3W_G": .010, "ERICK": .010, "TRACTOR": .018}
STATE_MIX_ADJ = {
    "TRACTOR": {"PB": 2.5, "HR": 2.5, "UP": 1.8, "MP": 1.8, "RJ": 1.8, "DL": 0, "CH": 0, "LD": 0, "AN": .3, "GA": .2,
                "PY": .3, "SK": .1, "MZ": .1, "NL": .2, "ML": .2, "AR": .2, "MN": .3, "LA": .2},
    "CAR": {"DL": 1.7, "CH": 1.8, "KL": 1.6, "GA": 1.5, "PY": 1.2, "HR": 1.3, "PB": 1.3, "MZ": 1.6, "NL": 1.8,
            "ML": 1.6, "AR": 1.8, "SK": 2.0, "LA": 1.8, "HP": 1.6, "JK": 1.4, "UK": 1.2, "BR": .7, "UP": .85, "OD": .8},
    "ERICK": {"DL": 3, "UP": 2.5, "BR": 3, "WB": 2.5, "AS": 2, "JH": 2, "KL": .1, "TN": .2, "KA": .3, "GA": .1,
              "MH": .3, "LA": 0, "SK": 0, "LD": 0},
    "3W_P": {"DL": 1.3, "MH": 1.3, "TN": 1.3, "KA": 1.3, "GJ": 1.2, "KL": 1.4, "TS": 1.3, "AP": 1.2, "HP": .3,
             "SK": .2, "AR": .2, "MZ": .3, "NL": .3, "LA": .1},
    "BUS": {"KL": 2.0, "TN": 1.4, "DL": 1.2},
}
_mix_cache = {}
def pick_class(state):
    wc = _mix_cache.get(state)
    if wc is None:
        wc = _mix_cache[state] = WChoice((c, BASE_MIX[c] * STATE_MIX_ADJ.get(c, {}).get(state, 1.0)) for c in CLASSES)
    return wc()

TRANSPORT = {"TAXI", "LCV", "TRUCK", "BUS", "3W_P", "3W_G", "ERICK"}

# Registration-date distribution: ~7%/yr fleet growth, COVID dip, festive (Oct-Nov) and March peaks.
_reg_days, _reg_w = [], []
_d = REG_START
while _d <= END:
    w = 1.07 ** (_d.year - 2008)
    if _d.year == 2020: w *= .72
    if _d.year == 2021: w *= .85
    if _d.month in (10, 11): w *= 1.3
    if _d.month == 3: w *= 1.12
    _reg_days.append(_d); _reg_w.append(w); _d += days(1)
REG_DAY = WChoice(zip(_reg_days, _reg_w))

# ----------------------------------------------------------------------------------------
# Make/model catalogue -- (maker, model, body, on-sale-from (y,m), until (y,m)|None, weight, fuels)
# Fuels: P petrol, D diesel, C CNG, L LPG, E electric, H strong hybrid. Dates approximate (month).
# ----------------------------------------------------------------------------------------
CAT = {
 "2W": [("Hero", "Splendor Plus", "Motorcycle", (2008, 1), None, 20, "P"), ("Hero", "HF Deluxe", "Motorcycle", (2008, 1), None, 10, "P"),
        ("Hero", "Passion Pro", "Motorcycle", (2008, 1), None, 4, "P"), ("Hero", "Glamour", "Motorcycle", (2008, 1), None, 3, "P"),
        ("Honda", "Activa", "Scooter", (2008, 1), None, 20, "P"), ("Honda", "Shine", "Motorcycle", (2008, 1), None, 10, "P"),
        ("Honda", "Dio", "Scooter", (2008, 1), None, 3, "P"), ("Honda", "Unicorn", "Motorcycle", (2008, 1), None, 2, "P"),
        ("Bajaj", "Pulsar", "Motorcycle", (2008, 1), None, 9, "P"), ("Bajaj", "Platina", "Motorcycle", (2008, 1), None, 6, "P"),
        ("Bajaj", "CT 100", "Motorcycle", (2008, 1), None, 3, "P"), ("TVS", "Jupiter", "Scooter", (2013, 9), None, 7, "P"),
        ("TVS", "Apache", "Motorcycle", (2008, 1), None, 4, "P"), ("TVS", "XL Super", "Moped", (2008, 1), (2015, 6), 3, "P"),
        ("TVS", "XL100", "Moped", (2015, 1), None, 4, "P"), ("TVS", "Raider", "Motorcycle", (2021, 9), None, 2, "P"),
        ("TVS", "Ntorq", "Scooter", (2018, 2), None, 2, "P"), ("Suzuki", "Access", "Scooter", (2008, 1), None, 5, "P"),
        ("Royal Enfield", "Classic 350", "Motorcycle", (2009, 11), None, 4, "P"), ("Royal Enfield", "Bullet 350", "Motorcycle", (2008, 1), None, 1, "P"),
        ("Yamaha", "FZ", "Motorcycle", (2008, 3), None, 2, "P"), ("Yamaha", "Fascino", "Scooter", (2015, 7), None, 1, "P"),
        ("Ola Electric", "S1", "Scooter", (2021, 12), None, 2.2, "E"), ("Ather", "450", "Scooter", (2018, 6), None, 1.0, "E"),
        ("TVS", "iQube", "Scooter", (2020, 1), None, 1.6, "E"), ("Bajaj", "Chetak", "Scooter", (2020, 1), None, 1.4, "E"),
        ("Hero Electric", "Optima", "Scooter", (2016, 1), (2023, 6), .6, "E")],
 "CAR": [("Maruti Suzuki", "Alto", "Hatchback", (2008, 1), None, 10, "PC"), ("Maruti Suzuki", "WagonR", "Hatchback", (2008, 1), None, 9, "PC"),
         ("Maruti Suzuki", "Swift", "Hatchback", (2008, 1), None, 10, "PD"), ("Maruti Suzuki", "Dzire", "Sedan", (2008, 3), None, 8, "PDC"),
         ("Maruti Suzuki", "Baleno", "Hatchback", (2015, 10), None, 7, "PC"), ("Maruti Suzuki", "Celerio", "Hatchback", (2014, 2), None, 3, "PC"),
         ("Maruti Suzuki", "Ertiga", "MUV", (2012, 4), None, 4, "PDC"), ("Maruti Suzuki", "Brezza", "SUV", (2016, 3), None, 5, "PD"),
         ("Maruti Suzuki", "Eeco", "Van", (2010, 1), None, 3, "PC"), ("Maruti Suzuki", "Fronx", "SUV", (2023, 4), None, 3, "PC"),
         ("Maruti Suzuki", "Grand Vitara", "SUV", (2022, 9), None, 2, "PH"), ("Hyundai", "i10", "Hatchback", (2008, 1), (2016, 12), 4, "P"),
         ("Hyundai", "Grand i10", "Hatchback", (2013, 9), None, 4, "PC"), ("Hyundai", "i20", "Hatchback", (2008, 12), None, 4, "PD"),
         ("Hyundai", "Creta", "SUV", (2015, 7), None, 6, "PD"), ("Hyundai", "Venue", "SUV", (2019, 5), None, 4, "PD"),
         ("Hyundai", "Verna", "Sedan", (2008, 1), None, 2, "PD"), ("Hyundai", "Santro", "Hatchback", (2008, 1), (2022, 6), 2, "PC"),
         ("Hyundai", "Exter", "SUV", (2023, 7), None, 1.5, "PC"), ("Tata", "Nexon", "SUV", (2017, 9), None, 5, "PDE"),
         ("Tata", "Punch", "SUV", (2021, 10), None, 4, "PCE"), ("Tata", "Tiago", "Hatchback", (2016, 4), None, 3, "PCE"),
         ("Tata", "Altroz", "Hatchback", (2020, 1), None, 2, "PD"), ("Tata", "Indica", "Hatchback", (2008, 1), (2018, 4), 2, "PD"),
         ("Tata", "Harrier", "SUV", (2019, 1), None, 1, "D"), ("Mahindra", "Bolero", "SUV", (2008, 1), None, 4, "D"),
         ("Mahindra", "Scorpio", "SUV", (2008, 1), None, 4, "D"), ("Mahindra", "XUV700", "SUV", (2021, 8), None, 2, "PD"),
         ("Mahindra", "Thar", "SUV", (2010, 10), None, 1.5, "PD"), ("Mahindra", "XUV300", "SUV", (2019, 2), (2024, 4), 1, "PD"),
         ("Mahindra", "XUV 3XO", "SUV", (2024, 5), None, 1, "PD"), ("Honda", "City", "Sedan", (2008, 1), None, 3, "PH"),
         ("Honda", "Amaze", "Sedan", (2013, 4), None, 2, "PD"), ("Honda", "Elevate", "SUV", (2023, 9), None, .7, "P"),
         ("Toyota", "Innova", "MUV", (2008, 1), None, 3, "D"), ("Toyota", "Fortuner", "SUV", (2009, 8), None, 1.5, "D"),
         ("Toyota", "Glanza", "Hatchback", (2019, 6), None, 1, "PC"), ("Kia", "Seltos", "SUV", (2019, 8), None, 2.5, "PD"),
         ("Kia", "Sonet", "SUV", (2020, 9), None, 2, "PD"), ("Kia", "Carens", "MUV", (2022, 2), None, 1, "PD"),
         ("Renault", "Kwid", "Hatchback", (2015, 9), None, 2, "P"), ("Nissan", "Magnite", "SUV", (2020, 12), None, 1, "P"),
         ("Skoda", "Kushaq", "SUV", (2021, 6), None, .5, "P"), ("Volkswagen", "Taigun", "SUV", (2021, 9), None, .5, "P"),
         ("MG", "Hector", "SUV", (2019, 6), None, 1, "PD"), ("MG", "Windsor EV", "SUV", (2024, 9), None, .7, "E")],
 "TAXI": [("Maruti Suzuki", "Dzire", "Sedan", (2008, 3), None, 10, "CD"), ("Maruti Suzuki", "WagonR", "Hatchback", (2008, 1), None, 4, "C"),
          ("Maruti Suzuki", "Ertiga", "MUV", (2012, 4), None, 6, "CD"), ("Toyota", "Innova", "MUV", (2008, 1), None, 5, "D"),
          ("Toyota", "Etios", "Sedan", (2011, 1), (2020, 4), 4, "D"), ("Tata", "Indica", "Hatchback", (2008, 1), (2018, 4), 4, "D")],
 "LCV": [("Tata", "Ace", "Mini Truck", (2008, 1), None, 10, "DC"), ("Mahindra", "Bolero Pik-Up", "Pickup", (2008, 1), None, 6, "D"),
         ("Ashok Leyland", "Dost", "Pickup", (2011, 9), None, 3, "D"), ("Maruti Suzuki", "Super Carry", "Mini Truck", (2016, 9), None, 2, "PC"),
         ("Tata", "Intra", "Pickup", (2019, 5), None, 2, "D"), ("Mahindra", "Supro", "Mini Truck", (2015, 10), None, 1.5, "DC"),
         ("Tata", "407", "LCV", (2008, 1), None, 2, "D"), ("Tata", "Ace EV", "Mini Truck", (2022, 5), None, .5, "E")],
 "TRUCK": [("Tata", "LPT 1613", "Truck", (2008, 1), None, 6, "D"), ("Tata", "Signa", "Truck", (2018, 1), None, 4, "D"),
           ("Ashok Leyland", "Ecomet", "Truck", (2012, 1), None, 4, "D"), ("Ashok Leyland", "2518", "Truck", (2008, 1), None, 4, "D"),
           ("BharatBenz", "1617R", "Truck", (2012, 9), None, 3, "D"), ("Eicher", "Pro 3015", "Truck", (2013, 6), None, 3, "D"),
           ("Mahindra", "Blazo", "Truck", (2016, 4), None, 2, "D")],
 "BUS": [("Tata", "Starbus", "Bus", (2008, 1), None, 6, "DC"), ("Ashok Leyland", "Lynx", "Bus", (2010, 1), None, 3, "D"),
         ("Ashok Leyland", "Viking", "Bus", (2008, 1), None, 4, "DC"), ("Eicher", "Skyline", "Bus", (2010, 1), None, 3, "D"),
         ("BharatBenz", "1624 Bus", "Bus", (2016, 1), None, 1, "D"), ("Olectra", "K9", "Bus", (2019, 3), None, .6, "E"),
         ("Tata", "Ultra EV", "Bus", (2021, 1), None, .4, "E")],
 "3W_P": [("Bajaj", "RE", "Auto Rickshaw", (2008, 1), None, 12, "CDLP"), ("Piaggio", "Ape City", "Auto Rickshaw", (2008, 1), None, 5, "CDL"),
          ("Mahindra", "Alfa", "Auto Rickshaw", (2008, 1), None, 2, "D"), ("TVS", "King", "Auto Rickshaw", (2008, 6), None, 2, "CL"),
          ("Mahindra", "Treo", "Auto Rickshaw", (2018, 11), None, 1.5, "E"), ("Piaggio", "Ape E-City", "Auto Rickshaw", (2019, 10), None, 1, "E")],
 "3W_G": [("Piaggio", "Ape Xtra", "Goods 3W", (2008, 1), None, 5, "DC"), ("Bajaj", "Maxima Cargo", "Goods 3W", (2015, 1), None, 3, "DC"),
          ("Mahindra", "Alfa Load", "Goods 3W", (2008, 1), None, 3, "D"), ("Mahindra", "Treo Zor", "Goods 3W", (2020, 10), None, 1, "E"),
          ("Euler", "HiLoad EV", "Goods 3W", (2021, 1), None, .5, "E")],
 "ERICK": [("YC Electric", "Yatri", "E-Rickshaw", (2015, 6), None, 5, "E"), ("Saera", "Mayuri", "E-Rickshaw", (2015, 6), None, 4, "E"),
           ("Mahindra", "e-Alfa Mini", "E-Rickshaw", (2017, 10), None, 2, "E"), ("Kinetic Green", "Safar", "E-Rickshaw", (2016, 1), None, 1, "E"),
           ("Lohia", "Humsafar", "E-Rickshaw", (2016, 1), None, 1, "E")],
 "TRACTOR": [("Mahindra", "575 DI", "Tractor", (2008, 1), None, 6, "D"), ("Swaraj", "744 FE", "Tractor", (2008, 1), None, 4, "D"),
             ("Sonalika", "DI 745", "Tractor", (2008, 1), None, 3, "D"), ("John Deere", "5050D", "Tractor", (2008, 1), None, 3, "D"),
             ("Eicher", "380", "Tractor", (2008, 1), None, 2, "D"), ("Massey Ferguson", "1035 DI", "Tractor", (2008, 1), None, 3, "D"),
             ("New Holland", "3630", "Tractor", (2008, 1), None, 2, "D"), ("Farmtrac", "45", "Tractor", (2008, 1), None, 1.5, "D")],
}
# EV share of new registrations by year (approximate ramp; see DATA_SOURCES.md)
EV_SHARE = {"2W": {2016: .001, 2017: .001, 2018: .002, 2019: .003, 2020: .004, 2021: .012, 2022: .04, 2023: .05, 2024: .055, 2025: .06, 2026: .065},
            "CAR": {2020: .002, 2021: .005, 2022: .01, 2023: .02, 2024: .025, 2025: .035, 2026: .04},
            "3W_P": {2019: .02, 2020: .05, 2021: .08, 2022: .15, 2023: .2, 2024: .25, 2025: .3, 2026: .32},
            "3W_G": {2020: .03, 2021: .06, 2022: .1, 2023: .14, 2024: .18, 2025: .22, 2026: .24},
            "LCV": {2022: .01, 2023: .02, 2024: .03, 2025: .04, 2026: .05},
            "BUS": {2019: .01, 2020: .02, 2021: .03, 2022: .05, 2023: .06, 2024: .07, 2025: .08, 2026: .09}}
FUEL_NAME = {"P": "Petrol", "D": "Diesel", "C": "Petrol/CNG", "L": "LPG", "E": "Electric", "H": "Strong Hybrid"}

def pick_model(cls, d):
    ym = (d.year, d.month)
    pool = [m for m in CAT[cls] if m[3] <= ym and (m[4] is None or ym <= m[4])]
    ev = EV_SHARE.get(cls, {}).get(d.year, 0.0)
    want_ev = R.random() < ev
    if cls != "ERICK":
        sub = [m for m in pool if ("E" in m[6]) == want_ev] if want_ev else [m for m in pool if m[6] != "E"]
        pool = sub or [m for m in pool if m[6] != "E"] or pool
    m = wpick([(m, m[5]) for m in pool])
    fuels = m[6]
    if want_ev and "E" in fuels: f = "E"
    elif fuels == "E": f = "E"
    else:
        diesel_w = .32 if d.year < 2020 else .17
        base = {"P": .6, "D": diesel_w, "C": .12, "L": .05, "H": .06}
        if cls in ("TAXI",): base = {"P": .1, "D": .45, "C": .55}
        if cls in ("3W_P", "3W_G"): base = {"P": .05, "D": .35, "C": .5, "L": .1}
        if cls in ("LCV", "TRUCK", "BUS"): base = {"D": .85, "C": .15, "P": .1}
        f = wpick([(c, base.get(c, .05)) for c in fuels if c != "E"])
    return m, FUEL_NAME[f]

COLOURS = {
    "2W": [("Black", 40), ("Red", 13), ("Blue", 11), ("Grey", 11), ("White", 9), ("Silver", 7), ("Orange", 3), ("Brown", 2), ("Yellow", 2), ("Green", 2)],
    "CAR": [("White", 42), ("Silver", 14), ("Grey", 12), ("Red", 8), ("Blue", 8), ("Black", 8), ("Brown", 4), ("Orange", 2), ("Beige", 2)],
    "TAXI": [("White", 80), ("Silver", 10), ("Yellow", 6), ("Grey", 4)],
    "LCV": [("White", 45), ("Blue", 15), ("Silver", 10), ("Yellow", 10), ("Red", 10), ("Green", 5), ("Grey", 5)],
    "TRUCK": [("Orange", 22), ("Yellow", 18), ("Red", 15), ("Blue", 15), ("White", 15), ("Green", 10), ("Grey", 5)],
    "BUS": [("White", 25), ("Blue", 20), ("Red", 15), ("Yellow", 15), ("Green", 15), ("Orange", 10)],
    "3W_P": [("Green-Yellow", 40), ("Black-Yellow", 30), ("Yellow", 20), ("Blue", 10)],
    "3W_G": [("Blue", 30), ("Yellow", 30), ("Green", 20), ("White", 20)],
    "ERICK": [("Blue", 35), ("Green", 30), ("Yellow", 20), ("Red", 15)],
    "TRACTOR": [("Red", 60), ("Blue", 20), ("Green", 15), ("Orange", 5)],
}
ANPR_COLOUR = {"Green-Yellow": "Green", "Black-Yellow": "Yellow", "Beige": "Silver", "Brown": "Brown"}
COLOUR_CONFUSE = {"White": ["Silver"], "Silver": ["White", "Grey"], "Grey": ["Silver", "Black"], "Black": ["Grey", "Blue"],
                  "Blue": ["Black"], "Red": ["Orange"], "Orange": ["Red", "Yellow"], "Yellow": ["Orange"], "Green": ["Blue"], "Brown": ["Grey"]}
ANPR_TYPE = {"Motorcycle": "Two-Wheeler", "Scooter": "Two-Wheeler", "Moped": "Two-Wheeler", "Hatchback": "Hatchback",
             "Sedan": "Sedan", "SUV": "SUV/MUV", "MUV": "SUV/MUV", "Van": "Van", "Mini Truck": "LCV", "Pickup": "LCV",
             "LCV": "LCV", "Truck": "Truck", "Bus": "Bus", "Auto Rickshaw": "Three-Wheeler", "Goods 3W": "Three-Wheeler",
             "E-Rickshaw": "E-Rickshaw", "Tractor": "Tractor"}
TYPE_CONFUSE = {"Hatchback": "Sedan", "Sedan": "Hatchback", "SUV/MUV": "Sedan", "Van": "LCV", "LCV": "Truck",
                "Truck": "LCV", "Bus": "Truck", "Three-Wheeler": "E-Rickshaw", "E-Rickshaw": "Three-Wheeler",
                "Two-Wheeler": "Two-Wheeler", "Tractor": "Truck"}
VAHAN_CLASS = {"2W": "M-Cycle/Scooter", "CAR": "Motor Car", "TAXI": "Motor Cab", "LCV": "Goods Carrier (LGV)",
               "TRUCK": "Goods Carrier (HGV)", "BUS": "Bus", "3W_P": "Three Wheeler (Passenger)",
               "3W_G": "Three Wheeler (Goods)", "ERICK": "e-Rickshaw (P)", "TRACTOR": "Agricultural Tractor"}
DELHI_CAT = {"2W": "S", "CAR": "C", "TAXI": "T", "LCV": "V", "TRUCK": "L", "BUS": "P", "3W_P": "R", "3W_G": "R",
             "ERICK": "E", "TRACTOR": "C"}

# ----------------------------------------------------------------------------------------
# Owner names: regional pools (plus pan-Indian pools weighted by approximate state demographics)
# ----------------------------------------------------------------------------------------
NP = {
 "hindi": (["Ravi", "Amit", "Suresh", "Rajesh", "Manoj", "Sanjay", "Vikram", "Rahul", "Vivek", "Ashok", "Deepak", "Anil", "Sunil", "Ramesh",
            "Naresh", "Mahesh", "Dinesh", "Yogesh", "Mukesh", "Rakesh", "Vishal", "Nitin", "Gaurav", "Rohit", "Ajay", "Pankaj", "Alok",
            "Ankit", "Sandeep", "Vijay", "Prakash", "Arvind", "Santosh", "Rajendra", "Pradeep", "Abhishek", "Shubham", "Aman", "Saurabh",
            "Hemant", "Brijesh", "Devendra", "Shyam", "Om Prakash", "Jitendra", "Kamlesh", "Lalit", "Ram Kumar", "Satish", "Harish"],
           ["Neha", "Priya", "Anita", "Pooja", "Kavita", "Sunita", "Rekha", "Seema", "Geeta", "Manju", "Ritu", "Preeti", "Swati", "Nisha",
            "Komal", "Shalini", "Nidhi", "Anjali", "Sarita", "Sushma", "Usha", "Kiran", "Radha", "Savita", "Poonam", "Meena", "Asha", "Mamta", "Jyoti"],
           ["Sharma", "Verma", "Singh", "Kumar", "Gupta", "Yadav", "Chauhan", "Tiwari", "Mishra", "Pandey", "Dubey", "Saxena", "Agarwal",
            "Bansal", "Jain", "Srivastava", "Tyagi", "Bhardwaj", "Shukla", "Tripathi", "Rajput", "Thakur", "Prajapati", "Maurya", "Kushwaha",
            "Chaudhary", "Rathore", "Solanki", "Rawat", "Negi", "Bisht", "Joshi", "Pathak", "Dixit", "Awasthi", "Meena", "Garg", "Mittal", "Goel"]),
 "punjab_hindu": (["Rajesh", "Sanjeev", "Vikas", "Anil", "Pawan", "Rohit", "Sunil", "Ashwani", "Deepak", "Vinod"],
                  ["Neha", "Anju", "Meenu", "Ritu", "Sonia", "Pooja", "Shilpa", "Monika"],
                  ["Arora", "Kapoor", "Malhotra", "Khanna", "Chopra", "Bhatia", "Sethi", "Mehra", "Ahuja", "Bedi", "Goyal", "Mittal", "Sharma"]),
 "sikh": (["Gurpreet", "Harpreet", "Manpreet", "Jaspreet", "Harjit", "Kuldeep", "Baljeet", "Navdeep", "Amritpal", "Harmanpreet",
           "Gurdeep", "Sukhwinder", "Paramjit", "Rajinder", "Jagdeep", "Lakhwinder", "Satnam", "Inderjit"],
          ["Jasleen", "Simran", "Harleen", "Navneet", "Rajwinder", "Gurleen", "Manpreet", "Sukhpreet", "Amandeep", "Kulwinder"],
          ["Sandhu", "Gill", "Sidhu", "Dhillon", "Brar", "Grewal", "Bajwa", "Randhawa", "Cheema", "Virk", "Mann", "Sekhon"]),
 "bengal": (["Debashish", "Subrata", "Amitava", "Partha", "Soumen", "Arindam", "Tapas", "Biswajit", "Sourav", "Abhijit", "Sandip",
             "Pranab", "Indranil", "Rajib", "Anirban", "Saikat", "Tanmoy", "Kaushik", "Suman", "Prasenjit"],
            ["Moushumi", "Bidisha", "Rina", "Mamata", "Sushmita", "Sreya", "Ananya", "Paromita", "Sharmistha", "Tanushree", "Payel",
             "Rituparna", "Madhumita", "Soma", "Dipannita"],
            ["Chatterjee", "Bose", "Banerjee", "Mukherjee", "Ganguly", "Sen", "Dasgupta", "Chakraborty", "Bhattacharya", "Roy", "Das",
             "Ghosh", "Dutta", "Mitra", "Sarkar", "Mondal", "Saha", "Pal", "Biswas", "Haldar", "Majumdar", "Sinha", "Nandi", "Kar"]),
 "assam": (["Hemanta", "Bikash", "Rijul", "Pranjal", "Dhruba", "Manab", "Nayan", "Jayanta", "Bhaskar", "Utpal", "Dipankar", "Pallab", "Mridul"],
           ["Pallavi", "Junmoni", "Nilakshi", "Barnali", "Jahnavi", "Priyanka", "Mousumi", "Rashmi", "Bornali", "Anamika"],
           ["Baruah", "Bora", "Gogoi", "Saikia", "Hazarika", "Deka", "Phukan", "Kalita", "Sarma", "Das", "Nath", "Talukdar", "Medhi", "Bhuyan"]),
 "odia": (["Subhash", "Prasanta", "Sanjeeb", "Debasis", "Bijay", "Ashok", "Manas", "Ranjan", "Pradeep", "Sarat", "Bikram", "Satyajit", "Biswanath"],
          ["Sasmita", "Pragyan", "Lipika", "Smita", "Mamata", "Sanghamitra", "Itishree", "Subhashree", "Puja", "Sabita"],
          ["Mohanty", "Nayak", "Sahoo", "Behera", "Panda", "Rout", "Patra", "Mishra", "Das", "Swain", "Jena", "Pradhan", "Mohapatra",
           "Biswal", "Dash", "Parida", "Barik"]),
 "marathi": (["Sachin", "Rohan", "Mangesh", "Prashant", "Sagar", "Nilesh", "Amol", "Sandeep", "Ganesh", "Rahul", "Vaibhav", "Tushar",
              "Swapnil", "Kiran", "Sunil", "Vinayak", "Omkar", "Pravin", "Ajit", "Dattatray"],
             ["Trupti", "Snehal", "Ashwini", "Pooja", "Prajakta", "Shital", "Madhuri", "Rupali", "Vaishali", "Manisha", "Smita", "Supriya",
              "Pallavi", "Sayali"],
             ["Deshmukh", "Kulkarni", "Patil", "Pawar", "Jadhav", "More", "Gaikwad", "Kadam", "Chavan", "Deshpande", "Bhosale", "Shinde",
              "Joshi", "Salunkhe", "Kale", "Mane", "Shirke", "Sawant", "Naik", "Wagh", "Gawande"]),
 "gujarati": (["Jignesh", "Hitesh", "Bhavesh", "Nikhil", "Paresh", "Mehul", "Chirag", "Ketan", "Dhaval", "Hardik", "Kalpesh", "Jayesh",
               "Nirav", "Pratik", "Bhargav", "Alpesh", "Rakesh", "Mukesh"],
              ["Bhavna", "Hetal", "Krupa", "Nisha", "Falguni", "Komal", "Dimple", "Jinal", "Ekta", "Payal", "Riddhi", "Mansi"],
              ["Patel", "Shah", "Mehta", "Desai", "Trivedi", "Vyas", "Joshi", "Doshi", "Thakkar", "Modi", "Parekh", "Parmar", "Chauhan",
               "Solanki", "Rathod", "Panchal", "Gohil", "Jadeja", "Prajapati", "Vaghela"]),
 "konkan": (["Prasad", "Sanjay", "Rohan", "Nilesh", "Sachin", "Amit", "Vishal"], ["Pooja", "Sneha", "Priya", "Shweta", "Prachi"],
            ["Naik", "Kamat", "Prabhu", "Sawant", "Gaonkar", "Shirodkar", "Desai", "Kenkre", "Salgaonkar", "Parab"]),
 "tamil": (["Karthik", "Senthil", "Murugan", "Saravanan", "Ganesh", "Prakash", "Arun", "Vignesh", "Suresh", "Balaji", "Rajesh", "Dinesh",
            "Manikandan", "Selvam", "Ramesh", "Gopal", "Sathish", "Kumaravel", "Venkatesh", "Ashok"],
           ["Lakshmi", "Priya", "Kavitha", "Deepa", "Divya", "Selvi", "Revathi", "Meena", "Gayathri", "Sangeetha", "Anitha", "Malathi",
            "Nithya", "Saranya", "Bhuvana"],
           ["Kumar", "Raj", "Murugan", "Pandian", "Rajan", "Subramanian", "Krishnan", "Natarajan", "Shanmugam", "Velu", "Ramasamy",
            "Arumugam", "Palanisamy", "Govindan", "Sundaram"]),
 "malayali": (["Anil", "Sunil", "Rajesh", "Vinod", "Sajeev", "Biju", "Shaji", "Suresh", "Arun", "Vishnu", "Sreejith", "Manoj", "Pradeep", "Rajeev"],
              ["Lakshmi", "Sreeja", "Divya", "Anjali", "Remya", "Sindhu", "Bindu", "Jaya", "Athira", "Aswathy"],
              ["Nair", "Menon", "Pillai", "Kurup", "Panicker", "Nambiar", "Warrier", "Kumar", "Das", "Krishnan"]),
 "kannada": (["Ramesh", "Suresh", "Mahesh", "Prakash", "Manjunath", "Raghavendra", "Naveen", "Praveen", "Shivakumar", "Basavaraj", "Girish",
              "Harish", "Srinivas", "Venkatesh", "Nagaraj", "Chandrashekar", "Kiran", "Santosh"],
             ["Lakshmi", "Savitha", "Shilpa", "Deepa", "Kavya", "Rashmi", "Sowmya", "Shruthi", "Pavithra", "Asha", "Bhavya", "Meghana"],
             ["Gowda", "Shetty", "Hegde", "Kamath", "Pai", "Bhat", "Rao", "Naik", "Patil", "Kulkarni", "Reddy", "Murthy", "Prasad", "Swamy"]),
 "telugu": (["Venkata Ramana", "Srinivas", "Ravi Kumar", "Suresh", "Naresh", "Mahesh", "Rajesh", "Kiran", "Praveen", "Sai Kumar",
             "Chandra Sekhar", "Prasad", "Nagaraju", "Ramesh", "Krishna", "Vamsi", "Anil", "Satyanarayana"],
            ["Lakshmi", "Padma", "Swathi", "Sravani", "Lavanya", "Sirisha", "Anusha", "Madhavi", "Vijaya", "Sunitha", "Bhavani", "Haritha"],
            ["Reddy", "Rao", "Naidu", "Chowdary", "Varma", "Raju", "Goud", "Yadav", "Sharma", "Setty", "Murthy", "Prasad"]),
 "kashmir_hindu": (["Rakesh", "Sanjay", "Vikram", "Rajesh", "Ashok", "Vijay"], ["Anjali", "Neha", "Ritu", "Sapna"],
                   ["Sharma", "Gupta", "Raina", "Kaul", "Dogra", "Jamwal", "Manhas", "Singh", "Koul", "Pandita"]),
 "northeast": (["Lalremruata", "Lalhmingliana", "Zothanpuia", "Vanlalhriata", "Temjen", "Akum", "Imkong", "Toshi", "Banshan", "Wanbor",
                "Kyrmen", "Rilang", "Tani", "Nabam", "Tage", "Kalling", "Bijen", "Premchand", "Tomba", "Herojit"],
               ["Lalrinpuii", "Lalnunmawii", "Zodinpuii", "Watisenla", "Atola", "Daphisha", "Ibashisha", "Evanisha", "Yamang", "Sanatombi", "Romita"],
               ["Ralte", "Hmar", "Pachuau", "Chhangte", "Sailo", "Ao", "Jamir", "Longkumer", "Imchen", "Lotha", "Lyngdoh", "Syiem",
                "Kharkongor", "Marak", "Sangma", "Nongrum", "Tara", "Taba", "Riba", "Pertin", "Laishram", "Ningthoujam"]),
 "sikkim": (["Pema", "Karma", "Sonam", "Dawa", "Nima", "Bikash", "Dorjee", "Tashi", "Phurba", "Sangay"], ["Dichen", "Anita", "Pema", "Yangchen", "Sarita"],
            ["Bhutia", "Lepcha", "Rai", "Gurung", "Tamang", "Pradhan", "Chettri", "Subba", "Sharma", "Limboo"]),
 "ladakh": (["Tsering", "Stanzin", "Rigzin", "Padma", "Dorjay", "Sonam", "Tashi", "Phuntsog"], ["Tsering", "Padma", "Diskit", "Rigzin"],
            ["Namgyal", "Dorjay", "Tundup", "Wangchuk", "Gyatso", "Angmo", "Dolma"]),
 "muslim": (["Mohammed", "Mohd", "Abdul", "Imran", "Farhan", "Salman", "Arif", "Javed", "Irfan", "Shahid", "Aamir", "Faisal", "Nadeem",
             "Rashid", "Sajid", "Wasim", "Zubair", "Aslam", "Iqbal", "Rizwan", "Shoaib", "Arshad", "Tariq", "Azhar", "Mohd Arif", "Abdul Rashid"],
            ["Ayesha", "Farida", "Shabana", "Nazia", "Rukhsar", "Sana", "Heena", "Shaheen", "Fatima", "Zainab", "Nasreen", "Shabnam",
             "Afreen", "Rubina", "Tabassum"],
            ["Khan", "Ansari", "Sheikh", "Qureshi", "Siddiqui", "Ahmed", "Hussain", "Ali", "Syed", "Pathan", "Shaikh", "Malik", "Mirza",
             "Rizvi", "Usmani"]),
 "kashmir_muslim": (["Mohammad Ashraf", "Ghulam Nabi", "Abdul Rashid", "Bilal", "Irfan", "Javid", "Shabir", "Mudasir", "Aijaz", "Farooq", "Tariq"],
                    ["Shabnam", "Rukhsana", "Nusrat", "Mehnaz", "Rubina", "Shazia", "Uzma"],
                    ["Bhat", "Dar", "Wani", "Lone", "Mir", "Shah", "Malik", "Sheikh", "Rather", "Ganie", "Khan"]),
 "christian": (["Joseph", "Thomas", "Mathew", "George", "Jose", "Sebastian", "Jacob", "Tomy", "Anthony", "Francis", "Peter", "Savio"],
               ["Mary", "Annie", "Elizabeth", "Jessy", "Liza", "Teena", "Sherin", "Maria", "Agnes", "Fatima"],
               ["Varghese", "Thomas", "Kurian", "Mathew", "Joseph", "Chacko", "Abraham", "Philip", "D'Souza", "Fernandes", "Pereira",
                "Rodrigues", "Gomes", "D'Costa", "Pinto", "Lobo", "Masih"]),
}
STATE_NAME_REGION = {k: s["name_region"] for k, s in STATES.items()}
MUSLIM = {"UP": .19, "BR": .17, "WB": .27, "AS": .34, "KL": .26, "JK": .68, "LA": .46, "LD": .96, "KA": .13, "MH": .115, "DL": .13,
          "GJ": .10, "RJ": .09, "MP": .07, "HR": .07, "UK": .14, "JH": .145, "TS": .127, "AP": .07, "TN": .06, "GA": .08, "PY": .06,
          "CH": .05, "DD": .05, "TR": .09, "MN": .08, "AN": .08}
CHRISTIAN = {"KL": .18, "GA": .25, "TN": .06, "PY": .06, "AN": .21, "KA": .02, "MH": .01}
SIKH = {"PB": .58, "CH": .13, "HR": .05, "DL": .03, "UK": .02, "JK": .02}

def make_person(state):
    female = R.random() < .15
    u = R.random()
    if state == "JK":
        pool = NP["kashmir_muslim"] if u < MUSLIM["JK"] else NP["kashmir_hindu"]
    elif state in ("NL", "MZ", "ML", "AR", "SK", "MN"):
        pool = NP[STATE_NAME_REGION[state]]
    elif u < MUSLIM.get(state, .04):
        pool = NP["muslim"]
    elif u < MUSLIM.get(state, .04) + CHRISTIAN.get(state, 0):
        pool = NP["christian"]
    elif u < MUSLIM.get(state, .04) + CHRISTIAN.get(state, 0) + SIKH.get(state, 0):
        pool = NP["sikh"]
        first = R.choice(pool[1] if female else pool[0])
        r2 = R.random()
        last = ("Kaur" if female else "Singh") if r2 < .55 else (R.choice(pool[2]) if r2 < .8 else
               ("Kaur " if female else "Singh ") + R.choice(pool[2]))
        return f"{first} {last}"
    else:
        reg = STATE_NAME_REGION.get(state, "hindi")
        if reg == "punjab": reg = "punjab_hindu"
        if reg == "kashmir": reg = "kashmir_hindu"
        pool = NP.get(reg, NP["hindi"])
    first = R.choice(pool[1] if female else pool[0]); last = R.choice(pool[2])
    reg = STATE_NAME_REGION.get(state, "")
    if pool is NP.get("tamil"):
        x = R.random()
        if x < .45: return f"{last[0]}. {first}"            # "R. Karthik" style (initial = father's name)
        if x < .60: return f"{first} {last[0]}"
    if pool is NP.get("telugu") and R.random() < .35: return f"{last[0]}. {first}"
    if pool is NP.get("kannada") and R.random() < .30: return f"{first} {last[0]}"
    if pool is NP.get("malayali") and R.random() < .25: return f"{first} {last[0]}"
    if reg == "northeast" and state == "MN" and pool is NP["northeast"] and R.random() < .6:
        return f"{first} {'Devi' if female else 'Singh'}"
    return f"{first} {last}"

SPELL = {"Mohammed": "Mohd", "Mohd": "Mohammed", "Mohammad": "Md.", "Lakshmi": "Laxmi", "Laxmi": "Lakshmi", "Srinivas": "Shrinivas",
         "Chowdary": "Choudhary", "Banerjee": "Banerji", "Mukherjee": "Mukherji", "Agarwal": "Aggarwal", "Shaikh": "Sheikh",
         "Sheikh": "Shaikh", "Chakraborty": "Chakravarty", "Bhattacharya": "Bhattacharjee", "Pandey": "Pande", "Saikia": "Saikiya",
         "Gowda": "Gouda", "Reddy": "Reddi", "Sharma": "Sarma", "Chaudhary": "Choudhary", "Jadhav": "Jadhao", "Kumar": "Kr."}
def name_variant(name):
    parts = name.split()
    x = R.random()
    if x < .35 and len(parts) >= 2:      # initials for given names
        return " ".join([p[0] + "." for p in parts[:-1]] + [parts[-1]])
    if x < .70:
        sw = [SPELL.get(p, p) for p in parts]
        if sw != parts: return " ".join(sw)
    if x < .85: return name.upper()
    if len(parts) == 2: return f"{parts[1]} {parts[0]}"
    return name.upper()

FLEET_KINDS = {"TAXI": ["Cabs Pvt Ltd", "Tours & Travels", "Travels", "Car Rentals"], "LCV": ["Logistics", "Transport Co.", "Carriers", "Enterprises", "Traders"],
               "TRUCK": ["Roadways", "Transport Co.", "Logistics Pvt Ltd", "Freight Carriers", "Carriers"], "BUS": ["Travels", "Bus Service", "Tours & Travels"],
               "CAR": ["Enterprises", "Infra Pvt Ltd", "Technologies Pvt Ltd", "Industries Ltd"], "3W_G": ["Traders", "Enterprises"],
               "3W_P": ["Auto Services"], "ERICK": ["E-Mobility", "Enterprises"], "TRACTOR": ["Agro Industries", "Farms"],
               "2W": ["Delivery Services Pvt Ltd", "Logistics"]}
FLEET_STEMS = ["Balaji", "Ganesh", "Laxmi", "Durga", "Krishna", "Sai", "Ambika", "Bharat", "National", "Golden", "City", "Jai Hind", "Shiv", "Hanuman", "Royal"]
OWNER_TYPE = {"2W": (.985, .012, .003), "CAR": (.90, .085, .015), "TAXI": (.45, .55, 0), "LCV": (.55, .43, .02), "TRUCK": (.40, .58, .02),
              "BUS": (.15, .45, .40), "3W_P": (.97, .03, 0), "3W_G": (.85, .15, 0), "ERICK": (.95, .05, 0), "TRACTOR": (.98, .02, 0)}
GOVT_DEPTS = ["Police Dept", "PWD", "Health Dept", "Transport Dept", "Forest Dept", "Municipal Corp."]
SHORT_STATE = {"Dadra and Nagar Haveli and Daman and Diu": "DNH & DD", "Andaman and Nicobar Islands": "A & N Islands", "Jammu and Kashmir": "J&K"}
_fleets = defaultdict(list)       # (state, group) -> [[name, size]]
_households = defaultdict(list)   # state -> [names]

def make_owner(state, cls):
    pi, pc, pg = OWNER_TYPE[cls]
    u = R.random()
    sname = STATES[state]["state_name"]
    sname = SHORT_STATE.get(sname, sname)
    if u < pg:
        if cls == "BUS": return "Government", f"{sname} State Transport Undertaking"
        return "Government", f"Govt. of {sname} - {R.choice(GOVT_DEPTS)}"
    if u < pg + pc:
        fl = _fleets[(state, cls)]
        if fl and R.random() < .7:
            f = wpick([(f, f[1]) for f in fl]); f[1] += 1
            return "Company", f[0]
        surname = R.choice(NP.get(STATE_NAME_REGION.get(state, "hindi"), NP["hindi"])[2]) if R.random() < .5 else R.choice(FLEET_STEMS)
        name = f"{R.choice(['', '', '', 'Sri ', 'Shree ', 'New ', 'Om ', 'Jai '])}{surname} {R.choice(FLEET_KINDS[cls])}"
        fl.append([name, 1])
        return "Company", name
    hh = _households[state]
    if hh and R.random() < .07:
        return "Individual", R.choice(hh)
    nm = make_person(state)
    if len(hh) < 4000: hh.append(nm)
    return "Individual", nm

# ----------------------------------------------------------------------------------------
# Insurers (names as they appear on policies; weights = rough motor book size, private/commercial)
# ----------------------------------------------------------------------------------------
INSURERS = [  # name, w_private, w_commercial, plate style used in that insurer's feed, code
    ("New India Assurance", 9, 12, "hyphen", "NIA"), ("ICICI Lombard", 10, 7, "hyphen", "ICL"), ("Bajaj Allianz", 8, 6, "compact", "BAG"),
    ("HDFC Ergo", 7, 5, "hyphen", "HDE"), ("Tata AIG", 8, 6, "hyphen", "TAG"), ("Go Digit", 7, 5, "space", "GOD"),
    ("United India Insurance", 6, 9, "hyphen_nopad", "UII"), ("Oriental Insurance", 4, 7, "hyphen", "OIC"),
    ("National Insurance", 4, 7, "hyphen", "NIC"), ("Reliance General", 4, 4, "hyphen", "RGI"), ("SBI General", 4, 3, "hyphen", "SBG"),
    ("Royal Sundaram", 2.5, 3, "hyphen", "RSA"), ("Cholamandalam MS", 3, 4, "compact", "CMS"), ("IFFCO Tokio", 4, 4, "hyphen", "ITG"),
    ("Acko", 3, .5, "compact", "ACK"), ("Zuno General", 1, .5, "hyphen", "ZNO"), ("Liberty General", 1.5, 1.5, "hyphen", "LGI"),
    ("Future Generali", 2, 2, "space", "FGI"), ("Universal Sompo", 1.5, 1.5, "hyphen", "USG"),
    ("Shriram General Insurance", 3, 8, "hyphen_pad_dl", "SGI"), ("Magma HDI General Insurance", 1.5, 3, "hyphen", "MHD"),
    ("Zurich Kotak General Insurance", 1.5, 1, "hyphen", "ZKG"), ("Navi General Insurance", .5, .2, "compact", "NGI"),
    ("Raheja QBE General Insurance", .3, .2, "hyphen", "RQB"), ("Bharti AXA General Insurance", 3, 2, "hyphen", "BAX")]
INS = {i[0]: i for i in INSURERS}
INS_PRIV_PRE = WChoice((i[0], i[1]) for i in INSURERS)
INS_PRIV_POST = WChoice((i[0], i[1]) for i in INSURERS if i[0] != "Bharti AXA General Insurance")
INS_COMM_PRE = WChoice((i[0], i[2]) for i in INSURERS)
INS_COMM_POST = WChoice((i[0], i[2]) for i in INSURERS if i[0] != "Bharti AXA General Insurance")
def pick_insurer(commercial, d, prev=None):
    if prev and R.random() < .62:
        if prev == "Bharti AXA General Insurance" and d > BHARTI_AXA_LAST: return "ICICI Lombard"
        return prev
    if d <= BHARTI_AXA_LAST: return (INS_COMM_PRE if commercial else INS_PRIV_PRE)()
    return (INS_COMM_POST if commercial else INS_PRIV_POST)()
def insurer_display(name, issued):
    if name == "Reliance General" and issued >= INDUSIND_FROM: return "IndusInd General Insurance"
    return name

# ----------------------------------------------------------------------------------------
# Behaviour parameters (calibrated -- see calibration_report.md)
# ----------------------------------------------------------------------------------------
LIFE_MEDIAN = {"2W": 11, "CAR": 15, "TAXI": 9, "LCV": 12, "TRUCK": 13, "BUS": 12, "3W_P": 9, "3W_G": 9, "ERICK": 5, "TRACTOR": 16}
DILIGENCE_MEAN = {"2W": .36, "CAR": .90, "TAXI": .95, "LCV": .88, "TRUCK": .90, "BUS": .95, "3W_P": .85, "3W_G": .82, "ERICK": .62, "TRACTOR": .62}
REENTRY_PER_YEAR = {"2W": .06, "CAR": .25, "TAXI": .4, "LCV": .3, "TRUCK": .35, "BUS": .4, "3W_P": .2, "3W_G": .2, "ERICK": .06, "TRACTOR": .05}
COMP_SHARE = {"2W": .55, "CAR": .85, "TAXI": .7, "LCV": .65, "TRUCK": .65, "BUS": .65, "3W_P": .45, "3W_G": .45, "ERICK": .3, "TRACTOR": .4}
THEFT_BASE = .0011    # per active vehicle-year (NCRB 2024: ~2.3 lakh thefts / ~40 crore registered vehicles)
THEFT_CLASS = {"2W": 1.25, "CAR": .6, "TAXI": .5, "LCV": .5, "TRUCK": .35, "BUS": .05, "3W_P": .5, "3W_G": .4, "ERICK": 1.6, "TRACTOR": .4}
RECOVERY_RATE = .22
LAM_CITY = {"2W": 10, "CAR": 14, "TAXI": 45, "LCV": 18, "TRUCK": 2, "BUS": 25, "3W_P": 30, "3W_G": 15, "ERICK": 22, "TRACTOR": 1}
LAM_TOLL = {"2W": 0, "CAR": 3, "TAXI": 10, "LCV": 5, "TRUCK": 36, "BUS": 18, "3W_P": .1, "3W_G": .5, "ERICK": 0, "TRACTOR": .8}
TRIP_LEN = {"TRUCK": (1, 5), "BUS": (1, 3), "CAR": (1, 3), "TAXI": (1, 3), "LCV": (1, 2), "3W_P": (1, 1), "3W_G": (1, 1), "TRACTOR": (1, 1), "2W": (1, 1), "ERICK": (1, 1)}
SPEED_KMH = {"TRUCK": 42, "BUS": 50, "CAR": 62, "TAXI": 62, "LCV": 48}
URBAN_BOOST = {"CAR": 1.2, "TAXI": 1.6, "3W_P": 1.3, "ERICK": 1.2, "TRACTOR": .3, "TRUCK": .6}

# ----------------------------------------------------------------------------------------
# Plates
# ----------------------------------------------------------------------------------------
def series_for(office, d, cls):
    idx = (d - REG_START).days // office["days_per_series"] + office["series_offset"]
    if cls in TRANSPORT: idx += 300                  # many states keep separate series for transport vehicles
    idx %= (24 * 24)
    if idx < 24 and d.year < 2012: return LETTERS[idx]
    return LETTERS[idx // 24] + LETTERS[idx % 24]

USED_PLATES = set()
def new_plate(state, office, d, cls, transport):
    for _ in range(50):
        if not transport and cls in ("CAR", "2W") and d >= BH_FROM and R.random() < (.02 if cls == "CAR" else .002):
            p = {"k": "BH", "yy": d.year % 100, "num": R.randint(1, 9999), "tail": R.choice(LETTERS) + R.choice(LETTERS)}
        elif office["plate_state_code"] == "DL":
            ser = series_for(office, d, cls)
            if len(ser) == 1 or R.random() < .1: ser = ser[-1]
            p = {"k": "DL", "ss": "DL", "rto": office["rto_number"], "cat": DELHI_CAT[cls], "ser": ser, "num": R.randint(1, 9999)}
        else:
            p = {"k": "STD", "ss": office["plate_state_code"], "rto": office["rto_number"], "ser": series_for(office, d, cls),
                 "num": R.randint(1, 9999)}
        c = pfmt(p, "compact")
        if c not in USED_PLATES:
            USED_PLATES.add(c); p["c"] = c
            return p
    raise RuntimeError("could not find a free plate")

def pfmt(p, style):
    k = p["k"]
    if k == "BH":
        if style in ("compact", "compact_lower"): s = f"{p['yy']:02d}BH{p['num']:04d}{p['tail']}"
        elif style == "space": s = f"{p['yy']:02d} BH {p['num']:04d} {p['tail']}"
        else: s = f"{p['yy']:02d}-BH-{p['num']:04d}-{p['tail']}"
    elif k == "DL":
        r, cs = p["rto"], p["cat"] + p["ser"]
        if style in ("compact", "compact_lower"): s = f"DL{r}{cs}{p['num']:04d}"
        elif style == "space": s = f"DL {r} {cs} {p['num']:04d}"
        elif style == "hyphen_pad_dl": s = f"DL-{r:02d}-{cs}-{p['num']:04d}"
        else: s = f"DL-{r}-{cs}-{p['num']:04d}"
    else:
        ss, r, ser, n = p["ss"], p["rto"], p["ser"], p["num"]
        if style in ("compact", "compact_lower"): s = f"{ss}{r:02d}{ser}{n:04d}"
        elif style == "space": s = f"{ss} {r:02d} {ser} {n:04d}"
        elif style == "hyphen_nopad": s = f"{ss}-{r}-{ser}-{n:04d}"
        else: s = f"{ss}-{r:02d}-{ser}-{n:04d}"
    return s.lower() if style == "compact_lower" else s

OCR_SWAP = {"0": "O", "O": "0", "1": "I", "I": "1", "8": "B", "B": "8", "5": "S", "S": "5", "2": "Z", "Z": "2", "6": "G",
            "G": "6", "D": "0", "Q": "0", "4": "A", "A": "4", "7": "T", "M": "N", "N": "M", "H": "M", "U": "V", "V": "U", "C": "G"}
def ocr_misread(s):
    idx = [i for i, ch in enumerate(s) if ch in OCR_SWAP]
    if not idx: return s
    i = R.choice(idx)
    return s[:i] + OCR_SWAP[s[i]] + s[i + 1:]
def typo(s):
    if len(s) < 4: return s
    i = R.randint(1, len(s) - 2)
    if R.random() < .5 and s[i] != " " and s[i + 1] != " " and s[i] != "-" and s[i + 1] != "-":
        return s[:i] + s[i + 1] + s[i] + s[i + 2:]
    ch = s[i]
    if ch.isdigit(): return s[:i] + str((int(ch) + R.choice([1, 9])) % 10) + s[i + 1:]
    return ocr_misread(s)

def make_vin(maker, d):
    h = stable_hash(maker)
    wmi = "M" + VIN_CHARS[h % 23] + VIN_CHARS[(h // 23) % 33]          # synthetic WMI ("M" = India range)
    vds = "".join(R.choice(VIN_CHARS) for _ in range(5))
    chk = R.choice("0123456789X")
    my = d.year - (1 if d.month <= 2 and R.random() < .3 else 0)
    return f"{wmi}{vds}{chk}{VIN_YEAR.get(my, 'T')}{R.choice(VIN_CHARS)}{R.randint(0, 999999):06d}"

# ----------------------------------------------------------------------------------------
# 1) Registry: vehicles, owners, life events
# ----------------------------------------------------------------------------------------
N = args.vehicles
print(f"Simulating {N:,} registered vehicles ...", flush=True)
V = []
for i in range(N):
    st = STATE_PICK()
    cls = pick_class(st)
    regd = REG_DAY()
    if cls == "ERICK" and regd < date(2015, 6, 1): cls = "3W_P"
    if regd.year < 2011 and cls == "3W_G" and R.random() < .3: cls = "LCV"
    transport = cls in TRANSPORT
    office = pick_office(st, regd, transport)
    (maker, model, body, *_), fuel = pick_model(cls, regd)
    colour = wpick(COLOURS[cls])
    if cls == "TRACTOR": colour = {"John Deere": "Green", "New Holland": "Blue"}.get(maker, colour)
    otype, owner = make_owner(st, cls)
    v = {"id": i, "state": st, "cls": cls, "reg": regd, "office": office, "transport": transport,
         "maker": maker, "model": model, "body": body, "fuel": fuel, "colour": colour, "otype": otype,
         "owners": [(regd, owner)], "vin": make_vin(maker, regd)}
    v["plate"] = new_plate(st, office, regd, cls, transport)
    # off-road (retirement) date -- vehicles leave the road without being de-registered
    life = math.exp(math.log(LIFE_MEDIAN[cls]) + R.gauss(0, .45))
    v["retire"] = regd + days(int(life * 365.25))
    # ownership transfers (individual owners only)
    if otype == "Individual":
        hz = {"2W": .03, "CAR": .05}.get(cls, .03)
        t = add_years(regd, 2)
        while t < END and len(v["owners"]) < 3:
            t = exp_after(t, hz, min(END, v["retire"]))
            if t is None: break
            v["owners"].append((t, make_person(st)))
    # owner diligence (propensity to renew); companies/government more diligent
    mu = DILIGENCE_MEAN[cls] + (.12 if otype != "Individual" else 0)
    mu = min(.97, mu); k = 5.0
    v["dil"] = R.betavariate(mu * k, (1 - mu) * k)
    V.append(v)

# --- theft (FIRs) ---
for v in V:
    st_mult = float(STATES[v["state"]]["theft_rate_multiplier"]) / _theft_norm
    h = THEFT_BASE * THEFT_CLASS[v["cls"]] * st_mult
    a = max(v["reg"], THEFT_FEED_FROM); b = min(v["retire"], END)
    v["theft"] = None
    if h <= 0 or a >= b: continue
    t = exp_after(a, h, b)
    if t is not None and t < b:
        rec = None
        if R.random() < RECOVERY_RATE:
            rec = t + days(max(1, int(R.expovariate(1 / 40.0))))
        v["theft"] = {"date": t, "rec": rec, "joyride": R.random() < .30}

# --- two demo events pinned inside the nightly-drop window (documented in README) ---
_c = [v for v in V if v["state"] == "DL" and v["cls"] == "2W" and not v["theft"] and v["reg"] < date(2024, 1, 1) and v["retire"] > END]
if _c:
    R.choice(_c)["theft"] = {"date": DROP_DAYS[1], "rec": None, "joyride": True}     # FIR on day 2, seen on camera day 3
_o = [v for v in V if v["theft"] and not v["theft"]["rec"] and date(2026, 1, 1) <= v["theft"]["date"] < date(2026, 10, 1)]
if _o:
    R.choice(_o)["theft"]["rec"] = DROP_DAYS[2]                                      # an open case recovered on day 3

# --- scrapping at RVSFs (SHREDDED) ---
for v in V:
    v["scrap"] = None
    if v["theft"] and not v["theft"]["rec"]: continue
    age15 = add_years(v["reg"], 15)
    if v["otype"] == "Government" and age15 <= END:
        start = max(age15, GOVT_15Y_FROM)
        if start <= END and R.random() < .8:
            sd = start + days(R.randint(0, 600))
            if sd <= END: v["scrap"] = sd
    else:
        elig = max(add_years(v["reg"], 10 if not v["transport"] else 12), SCRAP_FROM)
        if elig <= END:
            h = (.0004 if v["transport"] else .0002) * (2.0 if v["retire"] <= elig else 1.0)
            sd = exp_after(elig, h, END)
            if sd is not None: v["scrap"] = sd
    if v["scrap"]:
        lag = R.randint(0, 20) if R.random() < .78 else None    # 22%: RTO record never updated
        v["scrap_rto_update"] = v["scrap"] + days(lag) if lag is not None else None
        v["clone"] = R.random() < .08
        v["retire"] = min(v["retire"], v["scrap"])

def owner_at(v, d):
    nm = v["owners"][0][1]; serial = 1
    for k, (t, n) in enumerate(v["owners"]):
        if t <= d: nm, serial = n, k + 1
    return nm, serial

def stopped(v, d):
    """True if the vehicle cannot be renewed/used at date d (stolen & not yet recovered, or scrapped)."""
    th = v["theft"]
    if th and th["date"] <= d and (th["rec"] is None or th["rec"] > d): return True
    if v["scrap"] and v["scrap"] <= d: return True
    return False

# ----------------------------------------------------------------------------------------
# 2) Insurance timelines (third-party cover is what the law requires)
# ----------------------------------------------------------------------------------------
policy_seq = 0
POL = []          # all policies (truth); filtered into the feed later
def add_policy(v, start, end, ptype, ins, issued_dt, od_end, first=False):
    global policy_seq
    policy_seq += 1
    nm, _ = owner_at(v, issued_dt.date())
    POL.append({"v": v, "start": start, "end": end, "ptype": ptype, "ins": ins, "issued": issued_dt,
                "od_end": od_end, "insured": name_variant(nm) if R.random() < .08 else nm, "first": first,
                "num": f"{INS[ins][4]}-{issued_dt.year % 100:02d}-{policy_seq:09d}"})

HORIZON = END + days(25)
for v in V:
    cls, reg = v["cls"], v["reg"]
    commercial = v["transport"] or v["otype"] != "Individual"
    start = reg - days(R.randint(0, 4))
    if reg >= LT_TP_FROM and cls in ("2W", "CAR"): start = max(start, LT_TP_FROM)
    issued = datetime(start.year, start.month, start.day, R.randint(10, 19), R.randint(0, 59), R.randint(0, 59))
    ins = pick_insurer(commercial, start)
    comp_p = COMP_SHARE[cls]
    if cls == "2W" and reg >= LT_TP_FROM: tp_years, bundled = 5, R.random() < .72
    elif cls == "CAR" and reg >= LT_TP_FROM: tp_years, bundled = 3, R.random() < .88
    else: tp_years, bundled = 1, False
    end = add_years(start, tp_years) - days(1)
    if tp_years > 1:
        ptype = f"Bundled (1Y OD + {tp_years}Y TP)" if bundled else f"Long Term TP ({tp_years}Y)"
        od_end = add_years(start, 1) - days(1) if bundled else None
    else:
        comp = R.random() < comp_p
        ptype = "Comprehensive" if comp else "Third Party Only"
        od_end = end if comp else None
    add_policy(v, start, end, ptype, ins, issued, od_end, first=True)
    # standalone OD covers bought during the long-term TP years (these do NOT include TP)
    if bundled:
        for k in range(1, tp_years):
            s = add_years(start, k)
            if s > HORIZON or stopped(v, s) or v["retire"] <= s: break
            if R.random() < (.55 if cls == "CAR" else .18):
                iss = datetime(s.year, s.month, s.day, 11, 0, 0) - days(R.randint(0, 15))
                add_policy(v, s, add_years(s, 1) - days(1), "Standalone OD", pick_insurer(commercial, s, ins), iss,
                           add_years(s, 1) - days(1))
    # TP renewals
    t, prev = end, ins
    while t < HORIZON:
        if stopped(v, t): break
        dormant = v["retire"] <= t
        p = v["dil"] * (.05 if dormant else 1.0)
        if R.random() < p:
            u = R.random()
            gap = 0 if u < .80 else (R.randint(1, 30) if u < .95 else R.randint(31, 200))
        else:
            q = .005 if dormant else REENTRY_PER_YEAR[cls]
            gap = 30 + int(min(R.expovariate(q), 100.0) * 365.25)
        ns = t + days(1 + gap)
        if ns > HORIZON or stopped(v, ns) or (v["scrap"] and v["scrap"] <= ns): break
        if v["retire"] <= ns and R.random() > .05: break
        age = (ns - reg).days / 365.25
        comp = R.random() < comp_p * max(.3, 1 - .06 * age)
        ne = add_years(ns, 1) - days(1)
        if gap == 0:
            iss = datetime(ns.year, ns.month, ns.day, R.randint(9, 21), R.randint(0, 59), R.randint(0, 59)) - days(R.randint(1, 20))
        else:
            iss = datetime(ns.year, ns.month, ns.day, R.randint(9, 21), R.randint(0, 59), R.randint(0, 59))
        ins2 = pick_insurer(commercial, ns, prev)
        add_policy(v, ns, ne, "Comprehensive" if comp else "Third Party Only", ins2, iss, ne if comp else None)
        t, prev = ne, ins2

TP_TYPES = ("Comprehensive", "Third Party Only", "Bundled (1Y OD + 3Y TP)", "Bundled (1Y OD + 5Y TP)", "Long Term TP (3Y)", "Long Term TP (5Y)")
TP_BY_V = defaultdict(list)
for p in POL:
    if p["ptype"] in TP_TYPES: TP_BY_V[p["v"]["id"]].append((p["start"], p["end"], p["issued"]))
def has_tp(vid, d, as_of=None):
    for s, e, iss in TP_BY_V.get(vid, ()):
        if s <= d <= e and (as_of is None or iss <= as_of): return True
    return False

# ----------------------------------------------------------------------------------------
# 3) ANPR captures
# ----------------------------------------------------------------------------------------
CAP_DAYS = [CAP_START + days(i) for i in range((END - CAP_START).days + 1)]
SEASON = {1: 1.0, 2: 1.0, 3: 1.0, 4: .98, 5: .95, 6: .9, 7: .88, 8: .9, 9: .97, 10: 1.1, 11: 1.12, 12: 1.05}
def _cum(ws):
    out, acc = [], 0.0
    for w in ws: acc += w; out.append(acc)
    return out
CITY_CUM = _cum([SEASON[d.month] * (1.0 if d.weekday() < 5 else (.9 if d.weekday() == 5 else .72)) for d in CAP_DAYS])
TOLL_CUM = _cum([SEASON[d.month] * (.95 if d.weekday() < 4 else (1.12 if d.weekday() in (4, 5) else 1.05)) for d in CAP_DAYS])
def sample_day(cum, lo, hi):
    a = cum[lo - 1] if lo > 0 else 0.0
    return min(hi, bisect.bisect_right(cum, a + R.random() * (cum[hi] - a)))
HOURS = {
    "commute": [.2, .1, .1, .1, .15, .3, .6, 1.2, 2.0, 2.2, 1.8, 1.4, 1.3, 1.3, 1.3, 1.4, 1.7, 2.1, 2.3, 2.0, 1.5, 1.0, .6, .35],
    "night":   [1.6, 1.7, 1.7, 1.6, 1.4, 1.2, 1.0, .8, .7, .7, .7, .8, .8, .8, .8, .8, .9, 1.0, 1.1, 1.2, 1.3, 1.4, 1.5, 1.6],
    "day":     [.5, .4, .3, .3, .6, 1.0, 1.4, 1.6, 1.6, 1.4, 1.2, 1.1, 1.1, 1.1, 1.2, 1.3, 1.4, 1.5, 1.4, 1.2, 1.0, .9, .8, .6],
    "highway": [.3, .2, .2, .2, .4, .8, 1.2, 1.5, 1.6, 1.6, 1.5, 1.4, 1.3, 1.3, 1.4, 1.5, 1.6, 1.6, 1.4, 1.1, .8, .6, .5, .4],
    "farm":    [0, 0, 0, 0, 0, .2, .8, 1.4, 1.6, 1.6, 1.5, 1.4, 1.3, 1.3, 1.4, 1.4, 1.2, .9, .4, .1, 0, 0, 0, 0],
}
HOUR_PICK = {k: WChoice(enumerate(w)) for k, w in HOURS.items()}
def hour_profile(cls, kind):
    if cls == "TRACTOR": return "farm"
    if cls == "TRUCK": return "night"
    if cls == "BUS": return "day"
    return "highway" if kind == "toll" else "commute"

def cap_window(v):
    """Active windows (inclusive day indices into CAP_DAYS) during which the vehicle is on the road."""
    wins = []
    a = max(v["reg"], CAP_START)
    b = min(v["retire"] - days(1), END)
    th = v["theft"]
    if th:
        b1 = min(b, th["date"] - days(1))
        if a <= b1: wins.append((a, b1))
        if th["rec"]:
            a2 = max(th["rec"] + days(1), CAP_START)
            if a2 <= b: wins.append((a2, b))
    elif a <= b:
        wins.append((a, b))
    return [((x - CAP_START).days, (y - CAP_START).days) for x, y in wins]

CAPS = []  # raw events: (capture_dt, vehicle or None, plate_text, cam, kind, colour, vtype, flags)
def emit(v, plate_text, day_idx, kind, cam, colour, vtype, tag=""):
    d = CAP_DAYS[day_idx]
    h = HOUR_PICK[hour_profile(v["cls"] if v else "CAR", kind)]()
    ts = datetime(d.year, d.month, d.day, h, R.randint(0, 59), R.randint(0, 59))
    CAPS.append([ts, v, plate_text, cam, kind, colour, vtype, tag])

def anpr_colour(c, night):
    c = ANPR_COLOUR.get(c, c)
    if R.random() < (.12 if night else .05): return R.choice(COLOUR_CONFUSE.get(c, [c]))
    return c
def anpr_type(body):
    t = ANPR_TYPE[body]
    return TYPE_CONFUSE.get(t, t) if R.random() < .02 else t

def pick_toll(state, cls):
    home = .45 if cls == "TRUCK" else (.6 if cls == "BUS" else .55)
    u = R.random()
    if u < home and state in TOLL_STATE: return TOLL_STATE[state]()
    if u < home + .25:
        nb = [s for s in NEIGHBOURS.get(state, []) if s in TOLL_STATE]
        if nb: return TOLL_STATE[R.choice(nb)]()
    return TOLL_NATIONAL()

print("Simulating ANPR captures ...", flush=True)
def toll_trip(v, day_idx, plaza, cls, tag=""):
    d = CAP_DAYS[day_idx]
    h = HOUR_PICK[hour_profile(cls, "toll")]()
    t = datetime(d.year, d.month, d.day, h, R.randint(0, 59), R.randint(0, 59))
    for _ in range(R.randint(*TRIP_LEN.get(cls, (1, 1)))):
        CAPS.append([t, v, None, plaza, "toll", None, None, tag])
        km, nxt = R.choice(NEAR[plaza["plaza_id"]][:6])
        t = t + timedelta(minutes=int(km / SPEED_KMH.get(cls, 55) * 60 * R.uniform(1.0, 1.4)) + R.randint(5, 40))
        plaza = nxt

for v in V:
    wins = cap_window(v)
    cls, st = v["cls"], v["state"]
    m = math.exp(R.gauss(-.35, .95))
    city = None
    if st in CITY_PICK and R.random() < float(STATES[st]["camera_city_share"]) * URBAN_BOOST.get(cls, 1.0):
        city = CITY_PICK[st]()
    route = R.sample(CAMS_BY_CITY[city], min(3, len(CAMS_BY_CITY[city]))) if city else None
    own_plazas = [pick_toll(st, cls) for _ in range(4)] if LAM_TOLL[cls] > 0 else []
    lo_len, hi_len = TRIP_LEN.get(cls, (1, 1)); mean_len = (lo_len + hi_len) / 2
    for lo, hi in wins:
        yrs = (hi - lo + 1) / 365.0
        if city:
            for _ in range(poisson(LAM_CITY[cls] * m * yrs)):
                cam = R.choice(route) if R.random() < .75 else R.choice(CAMS_BY_CITY[city])
                emit(v, None, sample_day(CITY_CUM, lo, hi), "city", cam, None, None)
        elif st in CITY_PICK:
            for _ in range(poisson(LAM_CITY[cls] * .08 * m * yrs)):
                c2 = CITY_PICK[st]()
                emit(v, None, sample_day(CITY_CUM, lo, hi), "city", R.choice(CAMS_BY_CITY[c2]), None, None)
        if own_plazas:
            for _ in range(poisson(LAM_TOLL[cls] * m * yrs / mean_len)):
                start_plaza = R.choice(own_plazas) if R.random() < .85 else pick_toll(st, cls)
                toll_trip(v, sample_day(TOLL_CUM, lo, hi), start_plaza, cls)
    # stolen vehicles still being driven on their original plates -- they stay around one city
    th = v["theft"]
    if th and th["joyride"] and th["date"] >= CAP_START - days(150):
        last = min(th["date"] + days(150), (th["rec"] - days(1)) if th["rec"] else END, END)
        first = max(th["date"] + days(1), CAP_START)
        if first <= last:
            base = CITY_PICK[st]() if (st in CITY_PICK and R.random() < .7) else ALL_CITY_PICK()
            bstate = CITY_INFO[base][0]
            for _ in range(R.randint(1, 6)):
                di = sample_day(CITY_CUM, (first - CAP_START).days, (last - CAP_START).days)
                if cls != "2W" and bstate in TOLL_STATE and R.random() < .3:
                    toll_trip(v, di, TOLL_STATE[bstate](), cls, "stolen_in_use")
                else:
                    emit(v, None, di, "city", R.choice(CAMS_BY_CITY[base]), None, None, "stolen_in_use")
    # cloned plates of scrapped vehicles: a different vehicle carrying the dead plate, in one region
    if v["scrap"] and v.get("clone") and v["scrap"] < END:
        first = max(v["scrap"] + days(15), CAP_START)
        if first <= END:
            ctype = R.choice(["Hatchback", "Sedan", "SUV/MUV", "LCV", "Two-Wheeler", "Truck"])
            ccol = R.choice(["White", "Silver", "Black", "Red", "Blue", "Grey"])
            base = ALL_CITY_PICK(); bstate = CITY_INFO[base][0]
            for _ in range(R.randint(2, 10)):
                di = sample_day(TOLL_CUM, (first - CAP_START).days, len(CAP_DAYS) - 1)
                if ctype != "Two-Wheeler" and bstate in TOLL_STATE and R.random() < .4:
                    emit(v, None, di, "toll", TOLL_STATE[bstate](), ccol, ctype, "cloned_plate")
                else:
                    emit(v, None, di, "city", R.choice(CAMS_BY_CITY[base]), ccol, ctype, "cloned_plate")

# fake / unregistered plates (no registry record anywhere)
n_fake = int(len(CAPS) * .0015)
for _ in range(n_fake):
    st = STATE_PICK()
    off = pick_office(st, END, False)
    p = {"k": "STD", "ss": off["plate_state_code"], "rto": off["rto_number"], "ser": R.choice(LETTERS) + R.choice(LETTERS), "num": R.randint(1, 9999)}
    if off["plate_state_code"] == "DL": p = {"k": "DL", "ss": "DL", "rto": off["rto_number"], "cat": "C", "ser": "A" + R.choice(LETTERS), "num": R.randint(1, 9999)}
    txt = pfmt(p, "compact")
    if txt in USED_PLATES: continue
    di = R.randint(0, len(CAP_DAYS) - 1)
    cam = TOLL_NATIONAL() if R.random() < .5 else R.choice(CAMS_BY_CITY[ALL_CITY_PICK()])
    emit(None, txt, di, "toll" if "plaza_id" in cam else "city", cam, R.choice(["White", "Silver", "Black", "Red"]),
         R.choice(["Hatchback", "Sedan", "SUV/MUV", "Two-Wheeler"]), "fake_plate")

# finalise capture rows: ANPR read, OCR noise, duplicates, ingestion delay
print(f"Finalising {len(CAPS):,} capture events ...", flush=True)
CAP_ROWS = []
for ts, v, ptxt, cam, kind, col, vtype, tag in CAPS:
    night = ts.hour < 6 or ts.hour >= 19
    if v is not None:
        truth = v["plate"]["c"]
        col = col or anpr_colour(v["colour"], night)
        vtype = vtype or anpr_type(v["body"])
    else:
        truth = ptxt
    read, conf = truth, R.uniform(.86, .995) if not night else R.uniform(.80, .99)
    u = R.random()
    err = ""
    if u < .0025:
        read, conf, err = "", R.uniform(.05, .35), "unreadable"
    elif u < .0065:
        i = R.randint(0, len(truth) - 1); read, conf, err = truth[:i] + truth[i + 1:], R.uniform(.40, .70), "partial"
    elif u < (.0065 + (.035 if night else .018)):
        read, conf, err = ocr_misread(truth), R.uniform(.50, .86), "ocr_swap"
    if kind == "toll":
        loc, lat, lon, cst, cid = cam["location"], cam["latitude"], cam["longitude"], cam["state_name"], cam["plaza_id"]
    else:
        loc = f"{cam['city']} ITMS Junction {cam['camera_id'][-3:]}"
        lat, lon, cid = cam["latitude"], cam["longitude"], cam["camera_id"]
        cst = STATES[cam["state_key"]]["state_name"]
    x = R.random()
    delay = timedelta(seconds=R.randint(1, 120)) if x < .95 else (timedelta(minutes=R.randint(2, 60)) if x < .99 else timedelta(hours=R.randint(24, 72)))
    row = {"capture_time": ts, "plate_no": read, "location": loc, "vehicle_color": col, "vehicle_type": vtype,
           "camera_id": cid, "camera_type": "TOLL_ANPR" if kind == "toll" else "CITY_ANPR", "capture_state": cst,
           "latitude": lat, "longitude": lon, "ocr_confidence": f"{conf:.3f}", "ingested_at": ts + delay,
           "_v": v, "_truth": truth, "_err": err, "_tag": tag}
    CAP_ROWS.append(row)
    if kind == "toll" and R.random() < .01:       # adjacent-lane camera reads the same vehicle again
        dup = dict(row); dup["capture_time"] = ts + timedelta(seconds=R.randint(1, 3))
        dup["ocr_confidence"] = f"{min(.999, conf + R.uniform(-.05, .05)):.3f}"; dup["ingested_at"] = dup["capture_time"] + delay
        dup["_tag"] = (tag + ";" if tag else "") + "duplicate_read"
        CAP_ROWS.append(dup)
CAP_ROWS = [r for r in CAP_ROWS if r["ingested_at"] <= END_DT]
CAP_ROWS.sort(key=lambda r: (r["ingested_at"], r["capture_time"]))
for k, r in enumerate(CAP_ROWS, 1): r["capture_id"] = k

# ----------------------------------------------------------------------------------------
# 4) Calibration report (measured on the simulated truth, as of END)
# ----------------------------------------------------------------------------------------
def pct(a, b): return 100.0 * a / b if b else 0.0
live = [v for v in V if v["reg"] <= END and not (v["scrap"] and v["scrap"] <= END) and not (v["theft"] and not v["theft"]["rec"])]
by_cls = defaultdict(lambda: [0, 0])
for v in live:
    by_cls[v["cls"]][0] += 1
    if not has_tp(v["id"], END): by_cls[v["cls"]][1] += 1
tot_live = len(live); tot_unins = sum(x[1] for x in by_cls.values())
on_road = [r for r in CAP_ROWS if r["_v"] is not None and r["capture_time"].date() >= END - days(90) and not r["_tag"]]
onroad_v = {}
for r in on_road: onroad_v[r["_v"]["id"]] = r["_v"]
onroad_unins = sum(1 for v in onroad_v.values() if not has_tp(v["id"], END))
thefts = [v for v in V if v["theft"]]
onroad_cls = defaultdict(lambda: [0, 0])
for v in onroad_v.values():
    onroad_cls[v["cls"]][0] += 1
    if not has_tp(v["id"], END): onroad_cls[v["cls"]][1] += 1
theft_years = (END - THEFT_FEED_FROM).days / 365.25
first_lapse = [0, 0]
for p in POL:
    if p["first"] and p["v"]["cls"] == "2W" and p["ptype"] in TP_TYPES and date(2019, 1, 1) <= p["end"] <= date(2025, 10, 1):
        first_lapse[0] += 1
        if not has_tp(p["v"]["id"], p["end"] + days(30)): first_lapse[1] += 1
ANCHOR = {"2W": "66% in 2019-20 (IIB); lower now that 5-yr TP covers 2018+ bikes"}
lines = ["# Calibration report", "",
         f"Generated with `--vehicles {N} --seed {args.seed}`. Measured on the simulated ground truth as of {END}.", "",
         "## Fleet composition (registry)", "", "| Class | Share here | Official | Source |", "|---|---:|---:|---|"]
cls_cnt = Counter(v["cls"] for v in V)
groups = {"Two-wheelers": ["2W"], "Cars, jeeps & taxis": ["CAR", "TAXI"], "Goods vehicles": ["LCV", "TRUCK"], "Buses": ["BUS"],
          "Others (3W, e-rickshaw, tractor)": ["3W_P", "3W_G", "ERICK", "TRACTOR"]}
offic = {"Two-wheelers": 74.7, "Cars, jeeps & taxis": 13.4, "Goods vehicles": 4.4, "Buses": .7, "Others (3W, e-rickshaw, tractor)": 6.9}
for g, cl in groups.items():
    lines.append(f"| {g} | {pct(sum(cls_cnt[c] for c in cl), N):.1f}% | {offic[g]}% | MoRTH, as on 31-03-2020 |")
lines += ["", "## Uninsured share (no valid third-party cover on the as-of date)", "",
          "| Class | Registered | Uninsured (registry) | Seen on road (90d) | Uninsured (on road) | Official anchor |", "|---|---:|---:|---:|---:|---|"]
for c in CLASSES:
    n, u = by_cls[c]; n2, u2 = onroad_cls[c]
    lines.append(f"| {c} | {n:,} | {pct(u, n):.1f}% | {n2:,} | {pct(u2, n2):.1f}% | {ANCHOR.get(c, '')} |")
nn = sum(by_cls[c][0] for c in CLASSES if c != "2W"); uu = sum(by_cls[c][1] for c in CLASSES if c != "2W")
nn2 = sum(onroad_cls[c][0] for c in CLASSES if c != "2W"); uu2 = sum(onroad_cls[c][1] for c in CLASSES if c != "2W")
lines.append(f"| Non-two-wheelers | {nn:,} | {pct(uu, nn):.1f}% | {nn2:,} | {pct(uu2, nn2):.1f}% | ~30% in 2019-20 (back-solved from IIB 57% overall, 66% of 2W, 75% 2W share) |")
lines += [f"| **All** | {tot_live:,} | **{pct(tot_unins, tot_live):.1f}%** | {len(onroad_v):,} | **{pct(onroad_unins, len(onroad_v)):.1f}%** | 44% (VAHAN, Mar-2026) to 54-56% (Supreme Court, Aug-2026) |",
          "", "Official anchors for the registry figure: >44% uninsured (VAHAN data as of 6-Mar-2026, shared in the Rajya Sabha) and "
          "~54-56% (16.54 crore of 30.48 crore vehicles, recorded by the Supreme Court on 4-Aug-2026); IIB: 66% of two-wheelers (2019-20). "
          "The on-road share is lower because vehicles that have left the road (but were never de-registered) are mostly the uninsured ones.",
          "", f"- Two-wheelers whose first policy was not renewed within 30 days of expiry: {pct(first_lapse[1], first_lapse[0]):.1f}% "
          f"(IIB: about 52% of vehicles do not renew after the first year, mostly two-wheelers).", ""]
st_theft = Counter(v["state"] for v in thefts)
lines += ["## Theft", "",
          f"- Theft FIRs {THEFT_FEED_FROM.year}-{END.year}: {len(thefts):,} -> {len(thefts) / theft_years / N * 100:.3f}% of registered vehicles per year "
          f"(NCRB 2024: ~2.3 lakh thefts / ~40 crore vehicles = ~0.06%).",
          f"- Two-wheeler share of thefts: {pct(sum(1 for v in thefts if v['cls'] == '2W'), len(thefts)):.1f}% (NCRB 2017: 85.4% motorcycles/scooters).",
          f"- Delhi share of thefts: {pct(st_theft['DL'], len(thefts)):.1f}% (NCRB 2024: 40,139 of ~2.3 lakh = ~17.5%).",
          f"- Recovered: {pct(sum(1 for v in thefts if v['theft']['rec'] and v['theft']['rec'] <= END), len(thefts)):.1f}% (city police data: ~15-25%).",
          f"- Scrapped at RVSFs (SHREDDED): {sum(1 for v in V if v['scrap']):,} vehicles "
          f"({sum(1 for v in V if v['scrap'] and v['otype'] == 'Government')} government vehicles >15 years).", ""]
cap_v = [r for r in CAP_ROWS if r["_v"] is not None]
lines += ["## ANPR captures", "",
          f"- Rows: {len(CAP_ROWS):,} over {len(CAP_DAYS)} days from {len({r['camera_id'] for r in CAP_ROWS}):,} cameras "
          f"({sum(1 for r in CAP_ROWS if r['camera_type'] == 'TOLL_ANPR'):,} toll / {sum(1 for r in CAP_ROWS if r['camera_type'] == 'CITY_ANPR'):,} city).",
          f"- Distinct registered vehicles seen: {len({r['_v']['id'] for r in cap_v}):,} of {N:,}.",
          f"- Read errors: OCR swaps {pct(sum(1 for r in CAP_ROWS if r['_err'] == 'ocr_swap'), len(CAP_ROWS)):.2f}%, "
          f"partial {pct(sum(1 for r in CAP_ROWS if r['_err'] == 'partial'), len(CAP_ROWS)):.2f}%, "
          f"unreadable {pct(sum(1 for r in CAP_ROWS if r['_err'] == 'unreadable'), len(CAP_ROWS)):.2f}%; "
          f"duplicate lane reads {pct(sum(1 for r in CAP_ROWS if 'duplicate_read' in r['_tag']), len(CAP_ROWS)):.2f}%.",
          f"- Late arrivals (ingested >24h after capture): {pct(sum(1 for r in CAP_ROWS if r['ingested_at'] - r['capture_time'] > timedelta(hours=24)), len(CAP_ROWS)):.2f}%.",
          f"- Stolen vehicles caught on camera (original plate): {len({r['_v']['id'] for r in CAP_ROWS if r['_tag'].startswith('stolen_in_use')}):,}; "
          f"cloned plates of scrapped vehicles: {len({r['_v']['id'] for r in CAP_ROWS if r['_tag'].startswith('cloned_plate')}):,}; "
          f"fake plates: {sum(1 for r in CAP_ROWS if r['_tag'] == 'fake_plate'):,} reads.", ""]
by_type = Counter(r["vehicle_type"] for r in CAP_ROWS)
lines += ["| ANPR vehicle_type | Rows |", "|---|---:|"] + [f"| {k} | {n:,} |" for k, n in by_type.most_common()] + [""]
report = "\n".join(lines)
print(report)
if args.report_only:
    sys.exit(0)

# ----------------------------------------------------------------------------------------
# 5) Emit source rows -- base snapshot (as of BASE_CUTOFF) + daily drops
# ----------------------------------------------------------------------------------------
REG_COLS = ["reg_id", "reg_no", "owner_name", "make_model", "registration_date", "maker", "vehicle_class", "body_type", "fuel_type",
            "colour", "chassis_no", "rto_code", "rto_name", "state_name", "transport_category", "owner_type", "owner_serial",
            "reg_valid_upto", "reg_status", "last_updated"]
POL_COLS = ["policy_id", "vehicle_number", "insurer", "valid_from", "valid_to", "policy_number", "policy_type", "od_valid_to",
            "insured_name", "chassis_no", "issued_at"]
CAP_COLS = ["capture_id", "plate_no", "capture_time", "location", "vehicle_color", "vehicle_type", "camera_id", "camera_type",
            "capture_state", "latitude", "longitude", "ocr_confidence", "ingested_at"]
THF_COLS = ["case_id", "plate_number", "report_type", "report_date", "case_status", "recovery_date", "reference_no",
            "reporting_office", "state_name", "chassis_no", "make_model", "colour", "updated_at"]

# registrations ----------------------------------------------------------------------------
V_sorted = sorted([v for v in V if v["reg"] <= END], key=lambda v: (v["reg"], v["id"]))
for k, v in enumerate(V_sorted, 1): v["reg_id"] = k
def reg_valid_upto(v, as_of):
    if v["transport"]: return None, None
    vu = add_years(v["reg"], 15) - days(1)
    renewed = None
    if vu < as_of and v["retire"] > vu and stable_hash(v["vin"]) % 100 < 65:
        renewed = vu - days(stable_hash(v["vin"]) % 40); vu = add_years(vu, 5)
    return vu, renewed
def reg_row(v, as_of):
    nm, serial = owner_at(v, as_of)
    vu, renewed = reg_valid_upto(v, as_of)
    status, upd = "ACTIVE", v["reg"]
    for t, _ in v["owners"][1:]:
        if t <= as_of: upd = max(upd, t)
    if renewed and renewed <= as_of: upd = max(upd, renewed)
    if v["scrap"] and v.get("scrap_rto_update") and v["scrap_rto_update"] <= as_of:
        status, upd = "SCRAPPED", max(upd, v["scrap_rto_update"])
    o = v["office"]
    return {"reg_id": v["reg_id"], "reg_no": pfmt(v["plate"], "compact_lower"), "owner_name": nm,
            "make_model": f"{v['maker']} {v['model']}", "registration_date": iso(v["reg"]), "maker": v["maker"],
            "vehicle_class": VAHAN_CLASS[v["cls"]], "body_type": v["body"], "fuel_type": v["fuel"], "colour": v["colour"],
            "chassis_no": v["vin"], "rto_code": o["rto_code"], "rto_name": o["rto_name"], "state_name": STATES[v["state"]]["state_name"],
            "transport_category": "Transport" if v["transport"] else "Non-Transport", "owner_type": v["otype"], "owner_serial": serial,
            "reg_valid_upto": iso(vu), "reg_status": status, "last_updated": iso(upd)}
base_cut = BASE_CUTOFF.date()
REG_BASE = [reg_row(v, base_cut) for v in V_sorted if v["reg"] <= base_cut]
REG_DAILY = defaultdict(list)
for D in DROP_DAYS:
    for v in V_sorted:
        ev = v["reg"] == D or any(t == D for t, _ in v["owners"][1:]) or (v["scrap"] and v.get("scrap_rto_update") == D)
        if ev: REG_DAILY[D].append(reg_row(v, D))

# policies ---------------------------------------------------------------------------------
feed = [p for p in POL if p["end"] >= POLICY_FEED_FROM and p["issued"] <= END_DT]
feed.sort(key=lambda p: (p["issued"], p["num"]))
POL_BASE, POL_DAILY = [], defaultdict(list)
for k, p in enumerate(feed, 1):
    v = p["v"]
    style = INS[p["ins"]][3]
    if p["first"] and v["reg"] >= date(2018, 1, 1) and stable_hash(p["num"]) % 100 < 25:
        vn = "NEW"                                   # policy issued before the registration number was assigned
    else:
        vn = pfmt(v["plate"], style)
        if stable_hash(p["num"] + "t") % 1000 < 4: vn = typo(vn)
    row = {"policy_id": k, "vehicle_number": vn, "insurer": insurer_display(p["ins"], p["issued"].date()),
           "valid_from": iso(p["start"]), "valid_to": iso(p["end"]), "policy_number": p["num"], "policy_type": p["ptype"],
           "od_valid_to": iso(p["od_end"]), "insured_name": p["insured"], "chassis_no": v["vin"], "issued_at": isodt(p["issued"])}
    if p["issued"] <= BASE_CUTOFF: POL_BASE.append(row)
    elif p["issued"].date() in DROP_DAYS: POL_DAILY[p["issued"].date()].append(row)

# captures ---------------------------------------------------------------------------------
def cap_out(r):
    return {"capture_id": r["capture_id"], "plate_no": r["plate_no"], "capture_time": isodt(r["capture_time"]), "location": r["location"],
            "vehicle_color": r["vehicle_color"], "vehicle_type": r["vehicle_type"], "camera_id": r["camera_id"],
            "camera_type": r["camera_type"], "capture_state": r["capture_state"], "latitude": r["latitude"], "longitude": r["longitude"],
            "ocr_confidence": r["ocr_confidence"], "ingested_at": isodt(r["ingested_at"])}
CAP_BASE = [cap_out(r) for r in CAP_ROWS if r["ingested_at"] <= BASE_CUTOFF]
CAP_DAILY = defaultdict(list)
for r in CAP_ROWS:
    if r["ingested_at"] > BASE_CUTOFF: CAP_DAILY[r["ingested_at"].date()].append(cap_out(r))

# theft & shredding ------------------------------------------------------------------------
cases = []
for v in V:
    th = v["theft"]
    if th and th["date"] >= THEFT_FEED_FROM:
        cases.append(("STOLEN", th["date"], v))
    if v["scrap"]:
        cases.append(("SHREDDED", v["scrap"], v))
cases.sort(key=lambda c: (c[1], c[2]["id"]))
fir_seq = defaultdict(int); cod_seq = defaultdict(int)
CASES = []
for k, (rtype, d, v) in enumerate(cases, 1):
    nm = v["office"]["rto_name"]
    nm = nm.split(":", 1)[1] if ":" in nm else nm
    city = nm.split("/")[0].split(",")[0].split("(")[0].strip() or STATES[v["state"]]["state_name"]
    if rtype == "STOLEN":
        fir_seq[(v["state"], d.year)] += 1
        ref = f"FIR {fir_seq[(v['state'], d.year)]:04d}/{d.year}"
        office = f"PS {city}"
    else:
        cod_seq[d.year] += 1
        ref = f"COD/RVSF-{v['state']}/{d.year}/{cod_seq[d.year]:05d}"
        office = f"RVSF {STATES[v['state']]['state_name']} #{1 + stable_hash(v['vin']) % 3}"
    plate_txt = pfmt(v["plate"], "space")
    if stable_hash(v["vin"] + rtype) % 100 < 1: plate_txt = typo(plate_txt)
    CASES.append({"case_id": k, "rtype": rtype, "date": d, "v": v, "ref": ref, "office": office, "plate": plate_txt,
                  "chassis": v["vin"] if stable_hash(v["vin"] + "c") % 100 < 90 else ""})
def case_row(c, as_of):
    v, rec = c["v"], None
    if c["rtype"] == "STOLEN":
        r = v["theft"]["rec"]
        status = "RECOVERED" if (r and r <= as_of) else "OPEN"
        rec = r if status == "RECOVERED" else None
    else:
        status = "CLOSED"
    return {"case_id": c["case_id"], "plate_number": c["plate"], "report_type": c["rtype"], "report_date": iso(c["date"]),
            "case_status": status, "recovery_date": iso(rec), "reference_no": c["ref"], "reporting_office": c["office"],
            "state_name": STATES[v["state"]]["state_name"], "chassis_no": c["chassis"], "make_model": f"{v['maker']} {v['model']}",
            "colour": v["colour"], "updated_at": iso(rec or c["date"])}
THF_BASE = [case_row(c, base_cut) for c in CASES if c["date"] <= base_cut]
THF_DAILY = defaultdict(list)
for D in DROP_DAYS:
    for c in CASES:
        r = c["v"]["theft"]["rec"] if c["rtype"] == "STOLEN" else None
        if c["date"] == D or (r == D):
            THF_DAILY[D].append(case_row(c, D))

# ----------------------------------------------------------------------------------------
# 6) Write files
# ----------------------------------------------------------------------------------------
def write(path, cols, rows):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=cols, lineterminator="\n")
        w.writeheader()
        n = 0
        for r in rows:
            w.writerow({c: ("" if r.get(c) is None else r.get(c)) for c in cols}); n += 1
    return n
out = args.out
counts = {}
counts["registrations"] = write(os.path.join(out, "sources", "registrations.csv"), REG_COLS, REG_BASE)
counts["policies"] = write(os.path.join(out, "sources", "policies.csv"), POL_COLS, POL_BASE)
counts["capture_log"] = write(os.path.join(out, "sources", "capture_log.csv"), CAP_COLS, CAP_BASE)
counts["theft_shredding"] = write(os.path.join(out, "sources", "theft_shredding.csv"), THF_COLS, THF_BASE)
for D in DROP_DAYS:
    base = os.path.join(out, "daily", D.isoformat())
    write(os.path.join(base, "registrations.csv"), REG_COLS, REG_DAILY[D])
    write(os.path.join(base, "policies.csv"), POL_COLS, POL_DAILY[D])
    write(os.path.join(base, "capture_log.csv"), CAP_COLS, CAP_DAILY[D])
    write(os.path.join(base, "theft_shredding.csv"), THF_COLS, THF_DAILY[D])
with open(os.path.join(out, "calibration_report.md"), "w", encoding="utf-8") as f:
    f.write(report + "\n")
print("\nBase load (as of", BASE_CUTOFF, "):", ", ".join(f"{k} {n:,}" for k, n in counts.items()))
for D in DROP_DAYS:
    print(f"Daily drop {D}: registrations {len(REG_DAILY[D])}, policies {len(POL_DAILY[D])}, "
          f"captures {len(CAP_DAILY[D])}, theft_shredding {len(THF_DAILY[D])}")
