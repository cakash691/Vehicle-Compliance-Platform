"""Assign each NHAI toll plaza (lat/lon) to an Indian state using datameet state polygons."""
import csv, sys, re, shapefile
shp_path, toll_csv, out_csv = sys.argv[1], sys.argv[2], sys.argv[3]
sf = shapefile.Reader(shp_path)
fields = [f[0] for f in sf.fields[1:]]
polys = []
for sr in sf.shapeRecords():
    rec = dict(zip(fields, sr.record))
    name = rec.get('ST_NM') or rec.get('NAME_1') or str(rec)
    shp = sr.shape
    pts, parts = shp.points, list(shp.parts) + [len(shp.points)]
    rings = [pts[parts[i]:parts[i+1]] for i in range(len(parts)-1)]
    xs = [p[0] for p in pts]; ys = [p[1] for p in pts]
    polys.append((name, rings, (min(xs), min(ys), max(xs), max(ys))))
print('state polygons:', len(polys), sorted(p[0] for p in polys))

def inside(x, y, ring):
    c = False; n = len(ring); j = n - 1
    for i in range(n):
        xi, yi = ring[i]; xj, yj = ring[j]
        if ((yi > y) != (yj > y)) and (x < (xj - xi) * (y - yi) / (yj - yi + 1e-15) + xi):
            c = not c
        j = i
    return c

def locate(x, y):
    for name, rings, (a, b, c, d) in polys:
        if a <= x <= c and b <= y <= d:
            # even-odd over all rings handles holes
            cnt = sum(1 for r in rings if inside(x, y, r))
            if cnt % 2 == 1:
                return name
    return None

rows = list(csv.DictReader(open(toll_csv, encoding='utf-8')))
out = []
miss = 0
for r in rows:
    try:
        lat, lon = float(r['lat']), float(r['lon'])
    except ValueError:
        miss += 1; continue
    st = locate(lon, lat)
    if st is None:
        # nudge search: try small offsets (points on coast/border)
        for dx, dy in [(0.02,0),(-0.02,0),(0,0.02),(0,-0.02),(0.05,0.05),(-0.05,-0.05),(0.05,-0.05),(-0.05,0.05)]:
            st = locate(lon+dx, lat+dy)
            if st: break
    if st is None:
        miss += 1; continue
    tpd = r.get('traffic_per_day') or ''
    out.append({'plaza_id': r['id'], 'plaza_name': re.sub(r'\s+', ' ', r['name']).strip(), 'state_name': st,
                'latitude': f"{lat:.6f}", 'longitude': f"{lon:.6f}", 'project_type': r.get('project_type',''),
                'traffic_per_day': tpd if tpd.isdigit() else ''})
with open(out_csv, 'w', newline='', encoding='utf-8') as f:
    w = csv.DictWriter(f, fieldnames=list(out[0].keys())); w.writeheader(); w.writerows(out)
print('mapped', len(out), 'unmapped', miss)
from collections import Counter
print(Counter(o['state_name'] for o in out).most_common())
