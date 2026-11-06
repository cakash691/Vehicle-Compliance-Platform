"""Build curated reference CSVs used by the generator.
Inputs : India-Codes/csv/RTO.csv (tpbadgujar/India-Codes), toll_plazas_mapped.csv (NHAI TIS snapshot 2022-03-01 + datameet state polygons)
Outputs: ref/states.csv, ref/rto_offices.csv, ref/toll_plazas.csv, ref/city_cameras.csv
"""
import csv, re, sys, os
from collections import defaultdict
rto_src, toll_src, outdir = sys.argv[1], sys.argv[2], sys.argv[3]

# ---------------- states ----------------
# vehicles_2015_k: MoSPI Statistical Year Book 2015, Table 20.4 (registered motor vehicles as on 31-03-2015, thousands)
# JK split: Ladakh carved out of J&K (assumption: 30k of J&K's 1,244k). DD = D&NH (112) + Daman&Diu (100).
STATES = [
 # key, name, vehicles_2015_k, theft_mult, name_region, urban_share(camera-city coverage assumption)
 ("AN","Andaman and Nicobar Islands",102,1.0,"bengal",0.0),
 ("AP","Andhra Pradesh",7882,1.0,"telugu",0.15),
 ("AR","Arunachal Pradesh",151,1.0,"northeast",0.0),
 ("AS","Assam",2510,1.0,"assam",0.15),
 ("BR","Bihar",4778,1.0,"hindi",0.12),
 ("CH","Chandigarh",676,1.0,"punjab",0.95),
 ("CG","Chhattisgarh",4314,1.0,"hindi",0.15),
 ("DD","Dadra and Nagar Haveli and Daman and Diu",212,1.0,"gujarati",0.0),
 ("DL","Delhi",8851,4.2,"hindi",0.95),
 ("GA","Goa",1084,1.0,"konkan",0.30),
 ("GJ","Gujarat",18721,1.0,"gujarati",0.30),
 ("HR","Haryana",7928,1.0,"hindi",0.30),
 ("HP","Himachal Pradesh",1077,1.0,"hindi",0.0),
 ("JK","Jammu and Kashmir",1214,1.0,"kashmir",0.20),
 ("JH","Jharkhand",2066,1.0,"hindi",0.12),
 ("KA","Karnataka",14785,1.0,"kannada",0.45),
 ("KL","Kerala",9648,0.16,"malayali",0.25),
 ("LA","Ladakh",30,1.0,"ladakh",0.0),
 ("LD","Lakshadweep",14,0.0,"malayali",0.0),
 ("MP","Madhya Pradesh",11141,1.0,"hindi",0.20),
 ("MH","Maharashtra",25562,1.0,"marathi",0.35),
 ("MN","Manipur",307,1.0,"northeast",0.0),
 ("ML","Meghalaya",267,1.0,"northeast",0.0),
 ("MZ","Mizoram",151,1.0,"northeast",0.0),
 ("NL","Nagaland",334,1.0,"northeast",0.0),
 ("OD","Odisha",5219,1.0,"odia",0.12),
 ("PY","Puducherry",803,1.0,"tamil",0.50),
 ("PB","Punjab",6263,1.0,"punjab",0.15),
 ("RJ","Rajasthan",12379,1.0,"hindi",0.15),
 ("SK","Sikkim",43,1.0,"sikkim",0.0),
 ("TN","Tamil Nadu",22519,0.31,"tamil",0.35),
 ("TS","Telangana",7845,1.0,"telugu",0.45),
 ("TR","Tripura",282,1.0,"bengal",0.0),
 ("UP","Uttar Pradesh",21636,1.0,"hindi",0.18),
 ("UK","Uttarakhand",1827,1.0,"hindi",0.20),
 ("WB","West Bengal",7403,1.0,"bengal",0.25),
]
tot = sum(s[2] for s in STATES)
with open(os.path.join(outdir, "states.csv"), "w", newline="") as f:
    w = csv.writer(f)
    w.writerow(["state_key","state_name","vehicles_2015_thousands","vehicle_share","theft_rate_multiplier","name_region","camera_city_share"])
    for k,n,v,tm,reg,u in STATES:
        w.writerow([k,n,v,f"{v/tot:.6f}",tm,reg,u])
print("states:", len(STATES), "total_k:", tot)

# ---------------- RTO offices ----------------
STATE_FROM_SRC = {"Andaman & Nicobar Islands":"AN","Andhra Pradesh":"AP","Arunachal Pradesh":"AR","Assam":"AS","Bihar":"BR",
 "Chhattisgarh":"CG","Chandigarh":"CH","Daman and Diu":"DD","Dadra & Nagar Haveli":"DD","Delhi":"DL","Goa":"GA","Gujarat":"GJ",
 "Haryana":"HR","Himachal Pradesh":"HP","Jammu & Kashmir":"JK","Jharkhand":"JH","Karnataka":"KA","Kerala":"KL","Lakshadweep":"LD",
 "Madhya Pradesh":"MP","Maharashtra":"MH","Manipur":"MN","Meghalaya":"ML","Mizoram":"MZ","Nagaland":"NL","Orissa":"OD",
 "Pondicherry":"PY","Punjab":"PB","Rajasthan":"RJ","Sikkim":"SK","Tamil Nadu":"TN","Tripura":"TR","Uttarakhand":"UK",
 "Uttar Pradesh":"UP","West Bengal":"WB"}
SKIP_PAT = re.compile(r"not longer in use|to be allot|temporary|This series belongs|Government Vehicles|government vehicles|nonresident", re.I)
COMM_PAT = re.compile(r"commercial vehicles only|KSRTC|Road Transport Corporation|tourist buses", re.I)
TELANGANA_AP = {1,9,10,11,12,13,14,15,20,22,23,24,25,28,29,36}   # former AP codes for Telangana districts (pre-2014)
offices = []   # dict rows
def add(state_key, plate_state, num, name, vfrom="", vto="", comm=0, note=""):
    offices.append(dict(state_key=state_key, plate_state_code=plate_state, rto_number=num,
        rto_code=f"{plate_state}{num:02d}" if plate_state!="DL" else f"DL{num}", rto_name=name.strip(),
        valid_from=vfrom, valid_to=vto, commercial_only=comm, note=note))
for r in csv.DictReader(open(rto_src, encoding="utf-8", errors="replace")):
    raw, place, st = r["RegNo"].strip(), re.sub(r"\s+"," ",r["Place"]).strip(), r["State"].strip()
    if st not in STATE_FROM_SRC or SKIP_PAT.search(place): continue
    codes = re.findall(r"\b([A-Z]{2})(\d{1,2})\b", raw)
    if not codes or not re.fullmatch(r"[A-Z]{2}\d{1,2}( & [A-Z]{2}\d{1,2})?", raw): continue
    comm = 1 if COMM_PAT.search(place) else 0
    place = re.sub(r"\s*\(commercial vehicles only\)|\s*RTO is located.*$|\[\d+\]|\]\]", "", place).strip()
    for pc, num in codes:
        num = int(num); key = STATE_FROM_SRC[st]
        if pc == "UA": continue
        if pc == "DL" and num > 13: continue                       # DL14-DL18 in source are not Delhi RTOs
        if pc == "AP" and num in TELANGANA_AP:
            add("TS","AP",num,place,"","2014-06-01",comm,"former AP code, Telangana district (pre-bifurcation registrations)")
            continue
        if pc == "OR":
            add("OD","OR",num,place,"","2012-08-31",comm,"legacy OR prefix (pre Sep-2012 registrations)")
            add("OD","OD",num,place,"2012-09-01","",comm,"")
            continue
        if pc == "DN":
            add("DD","DN",num,place,"","",comm,"legacy DN prefix (Silvassa)")
            continue
        add(key, pc, num, place, "", "", comm, "")
# Telangana TS (2014-06-02 .. 2024-03-14) and TG (2024-03-15 ..): RTA codes 01-38
TS_NAMES = {1:"Adilabad",9:"Khairatabad, Hyderabad",10:"Secunderabad, Hyderabad",11:"Malakpet, Hyderabad",
            12:"Bahadurpura, Hyderabad",13:"Mehdipatnam, Hyderabad",38:"Narayanpet"}
for n in range(1,39):
    nm = TS_NAMES.get(n, f"Telangana RTA {n:02d}")
    add("TS","TS",n,nm,"2014-06-02","2024-03-14",0,"")
    add("TS","TG",n,nm,"2024-03-15","",0,"")
add("OD","OD",33,"Bhubaneswar-II (Patia)","2012-09-01","",0,"")
# Ladakh: JK07 Kargil / JK10 Leh before the UT (2019-10-31); LA codes after
for o in offices:
    if o["state_key"]=="JK" and o["plate_state_code"]=="JK" and o["rto_number"] in (7,10):
        o["state_key"]="LA"; o["valid_to"]="2019-10-30"; o["note"]="Ladakh vehicle registered under J&K code before UT formation"
add("LA","LA",1,"Leh (Ladakh UT)","2019-10-31","",0,"")
add("LA","LA",2,"Kargil (Ladakh UT)","2019-10-31","",0,"")
# de-duplicate by (plate_state_code, rto_number, valid_from)
seen=set(); uniq=[]
for o in offices:
    k=(o["plate_state_code"],o["rto_number"],o["valid_from"])
    if k in seen: continue
    seen.add(k); uniq.append(o)
offices = uniq
cnt = defaultdict(int)
for o in offices: cnt[o["state_key"]]+=1
missing = [s[0] for s in STATES if cnt[s[0]]==0]
print("rto offices:", len(offices), "states missing:", missing)
with open(os.path.join(outdir,"rto_offices.csv"),"w",newline="") as f:
    w=csv.DictWriter(f, fieldnames=list(offices[0].keys())); w.writeheader(); w.writerows(offices)

# ---------------- toll plazas ----------------
NAME2KEY = {"Andaman & Nicobar":"AN","Jammu & Kashmir":"JK","Dadra and Nagar Haveli and Daman and Diu":"DD"}
for k,n,*_ in STATES: NAME2KEY.setdefault(n,k)
rows=[]
for r in csv.DictReader(open(toll_src, encoding="utf-8")):
    k = NAME2KEY.get(r["state_name"])
    if not k: print("unmapped state", r["state_name"]); continue
    nm = r["plaza_name"].replace("**","").strip()
    rows.append(dict(plaza_id=f"NHAI-{int(r['plaza_id']):04d}", plaza_name=nm, state_key=k, state_name=dict((s[0],s[1]) for s in STATES)[k],
                     latitude=r["latitude"], longitude=r["longitude"], project_type=r["project_type"], traffic_per_day=r["traffic_per_day"]))
with open(os.path.join(outdir,"toll_plazas.csv"),"w",newline="",encoding="utf-8") as f:
    w=csv.DictWriter(f, fieldnames=list(rows[0].keys())); w.writeheader(); w.writerows(rows)
print("toll plazas:", len(rows))

# ---------------- city ANPR camera sites (synthetic cameras at approximate real city-centre coordinates) ----------------
CITIES = [("Delhi","DL",28.6139,77.2090,13.7),("Bengaluru","KA",12.9716,77.5946,10.4),("Chennai","TN",13.0827,80.2707,6.6),
 ("Hyderabad","TS",17.3850,78.4867,7.0),("Mumbai","MH",19.0760,72.8777,4.0),("Pune","MH",18.5204,73.8567,4.0),
 ("Ahmedabad","GJ",23.0225,72.5714,4.9),("Kolkata","WB",22.5726,88.3639,4.0),("Jaipur","RJ",26.9124,75.7873,3.0),
 ("Lucknow","UP",26.8467,80.9462,2.5),("Kanpur","UP",26.4499,80.3319,1.5),("Ghaziabad","UP",28.6692,77.4538,1.5),
 ("Noida","UP",28.5355,77.3910,1.2),("Agra","UP",27.1767,78.0081,1.36),("Varanasi","UP",25.3176,82.9739,0.9),
 ("Gurugram","HR",28.4595,77.0266,2.0),("Faridabad","HR",28.4089,77.3178,1.0),("Chandigarh","CH",30.7333,76.7794,1.1),
 ("Ludhiana","PB",30.9010,75.8573,1.5),("Surat","GJ",21.1702,72.8311,2.5),("Vadodara","GJ",22.3072,73.1812,1.5),
 ("Indore","MP",22.7196,75.8577,2.0),("Bhopal","MP",23.2599,77.4126,1.6),("Nagpur","MH",21.1458,79.0882,1.8),
 ("Patna","BR",25.5941,85.1376,1.5),("Coimbatore","TN",11.0168,76.9558,2.5),("Madurai","TN",9.9252,78.1198,1.2),
 ("Kochi","KL",9.9312,76.2673,1.5),("Thiruvananthapuram","KL",8.5241,76.9366,1.4),("Visakhapatnam","AP",17.6868,83.2185,1.2),
 ("Vijayawada","AP",16.5062,80.6480,1.2),("Bhubaneswar","OD",20.2961,85.8245,1.0),("Guwahati","AS",26.1445,91.7362,1.0),
 ("Raipur","CG",21.2514,81.6296,1.0),("Ranchi","JH",23.3441,85.3096,0.8),("Dehradun","UK",30.3165,78.0322,0.8),
 ("Mysuru","KA",12.2958,76.6394,0.8),("Srinagar","JK",34.0837,74.7973,0.6),("Panaji","GA",15.4909,73.8278,0.5),
 ("Puducherry","PY",11.9416,79.8083,0.5)]
import random
rnd = random.Random(7)
cams=[]
for city,st,lat,lon,wt in CITIES:
    n = max(6, int(round(wt*6)))
    for i in range(1,n+1):
        cams.append(dict(camera_id=f"ITMS-{city[:3].upper()}-{i:03d}", city=city, state_key=st,
            latitude=f"{lat+rnd.uniform(-0.07,0.07):.6f}", longitude=f"{lon+rnd.uniform(-0.07,0.07):.6f}", city_weight=wt))
with open(os.path.join(outdir,"city_cameras.csv"),"w",newline="") as f:
    w=csv.DictWriter(f, fieldnames=list(cams[0].keys())); w.writeheader(); w.writerows(cams)
print("city cameras:", len(cams), "cities:", len(CITIES))
