# Where every number comes from

The v2 records are simulated, because real per-vehicle registration and insurance records
are not public in India. What makes them defensible is that each distribution is pinned to
a published figure, and the reference data (RTO codes, NHAI toll plazas) is real. This file
lists both, followed by the parts that are assumptions.

`calibration_report.md` shows how close the generated data lands to each figure.

## 1. Calibration anchors (official or widely reported figures)

| What | Figure used | Source |
|---|---|---|
| Fleet mix | 2W 74.7%, cars/jeeps/taxis 13.4%, goods 4.4%, buses 0.7%, others 6.9% (as on 31-03-2020) | MoRTH Road Transport Year Book, via Dataful: https://dataful.in/datasets/20224/ |
| State weights | Registered vehicles by state/UT as on 31-03-2015. This is the latest *complete* official state table I could access; rank order matches recent anchors such as Maharashtra 37.8 M in FY2020 | MoSPI Statistical Year Book 2015, Table 20.4, reproduced at https://en.wikipedia.org/wiki/Indian_states_ranking_by_number_of_vehicles |
| Uninsured share, current | "More than 44%" of vehicles without active insurance (VAHAN, as of 6-Mar-2026, shared in the Rajya Sabha) | https://carkhabri.com/carblogs/44--vehicles-in-india-are-running-without-insurance |
| Uninsured share, current | ~56%: 16.54 crore of 30.48 crore vehicles, recorded by the Supreme Court on 4-Aug-2026 (*National Insurance Co. v. Thungala Dhana Laxmi*, 2026 INSC 793) | https://www.thelawadvice.com/news/sc-orders-automatic-e-challans-for-uninsured-vehicles-directs-4-year-insurance-for-new-cars-6-years-for-two-wheelers |
| Uninsured two-wheelers | 66% (IIB Motor Annual Report, 2019-20); 57% overall; about 52% do not renew after the first year | https://www.nationalheraldindia.com/india/massive-number-of-vehicles-ply-on-road-without-valid-insurance-policy-irdai-worried ; https://bimabazaar.com/?p=12683 |
| Registered vs insured | 38.51 crore registered vehicles (30-Nov-2023); 17.54 crore insured (IIB) | Lok Sabha answer, reported at https://swarajyamag.com/amp/story/news-brief/over-1824-crore-e-challans-issued-in-india-in-four-years-rs-12632-crore-collected-tamil-nadu-leads-in-volume-up-in-revenue |
| Long-term third-party cover | New cars 3 years and new two-wheelers 5 years, for vehicles sold from 1-Sep-2018 (SC order of 20-Jul-2018) | https://www.mondaq.com/india/insurance-laws-and-products/724138/long-term-motor-insurance-for-third-party-liability |
| Theft rate | 2.3 lakh+ vehicles stolen in 2024; Delhi 40,139, Tamil Nadu 7,663, Kerala 1,701 (NCRB) | https://keralakaumudi.com/en/india/general/one-vehicle-stolen-every-2.3-minutes-in-india-ncrb-data-shows-1790711 ; https://vahanbazaar.in/news/vehicle-stolen-every-2-3-minutes-india-recovery-2026 |
| Theft by type | Motorcycles and scooters are 85.4% of motor-vehicle theft cases (NCRB 2017) | https://factly.in/ncrb-theft-data-up-to-2017 |
| Theft recovery | About 15-25% recovered: Chandigarh 2023 had 258 of 1,164; Bhopal Jan-Aug 2026 had 182 of 1,157 | https://www.tribuneindia.com/news/chandigarh/3-vehicles-stolen-every-day-in-chandigarh-busy-markets-targeted/amp ; https://www.freepressjournal.in/bhopal/bhopals-govindpura-records-100-two-wheeler-thefts-in-eight-months-highest-in-city |
| Scrapping | Government vehicles older than 15 years are deregistered and scrapped from 1-Apr-2023; only 11,025 vehicles had been scrapped at RVSFs by 31-Mar-2023 | https://lawyered.in/legal-disrupt/articles/analysis-new-motor-vehicle-act-provisions-which-will-be-effective-april-1-2023 ; https://www.deccanherald.com/amp/story/india%2F11000-old-vehicles-junked-under-vehicle-scrapping-policy-gadkari-1207086.html |

## 2. Real-world rules the data follows

| Rule | Source |
|---|---|
| Plate = state code + 2-digit RTO + series + 4 digits. Delhi omits the leading zero and adds a class letter: S two-wheeler, C car, R three-wheeler, P bus, T tourist, V van/pickup, E electric | https://www.bankbazaar.com/driving-licence/vehicle-number-plate.html ; https://indianlawwatch.com/wp-content/uploads/2022/06/vehicle-registration-plates-of-india.pdf |
| BH series `YY BH #### XX` from 15-Sep-2021, non-transport vehicles only, letters exclude I and O | https://www.bankbazaar.com/driving-licence/bharat-series-number-plates.html ; https://embed2.zeenews.com/auto/bharat-series-number-plate-all-you-need-to-about-new-interstate-bh-series-2451990.html |
| Telangana: AP codes before the 2014 split, TS until 14-Mar-2024, TG from 15-Mar-2024 (TG-01 Adilabad to TG-38 Narayanpet). Old plates keep their code | https://telanganatoday.com/tg-series-for-new-vehicle-registration-from-friday ; https://ommcomnews.com/india-news/new-vehicles-in-telangana-will-now-use-tg-prefix/ |
| Odisha: OR prefix before the rename, OD for new registrations (switch date used: 1-Sep-2012). OR plates stay valid | https://bajajfinservmarkets.in/resources/rto/rto-odisha ; https://www.zurichkotak.com/knowledge-center/rto/bhubaneswar-ii-od-33 |
| Bharti AXA General merged into ICICI Lombard on 8-Sep-2021 (no Bharti AXA policies are issued after that) | https://axa.com/press/press-releases/axa-and-bharti-have-completed-the-combination-of-their-non-life-operations-in-india-into-icici-lombard |
| Reliance General was renamed IndusInd General Insurance on 22-Sep-2025, so the feed has both names | https://rhnvrm.github.io/stock-market-circulars/circulars/bse/2025/bse-2025-10-23-e55e76ef566cb4a6-change-in-name-of-the-company-reliance-general-insurance-company-ltd |
| Private registration certificate valid 15 years, renewable in 5-year blocks | https://www.zurichkotak.com/knowledge-center/rto/bhubaneswar-ii-od-33 |

## 3. Real reference data shipped in `ref/`

| File | What | Origin |
|---|---|---|
| `toll_plazas.csv` | 701 real NHAI toll plazas with coordinates and daily traffic where published | NHAI Toll Information System snapshot of 01-03-2022, from https://github.com/geohacker/toll-plazas-india. Each plaza was assigned to a state by point-in-polygon against https://github.com/datameet/maps (`States/Admin2.shp`); 11 plazas with unusable coordinates were dropped. Names are kept as published, typos included |
| `rto_offices.csv` | 1,158 RTO codes with office names, including the legacy codes above | https://github.com/tpbadgujar/India-Codes (Wikipedia-derived), cleaned: removed codes marked "no longer in use", non-RTO DL14-DL18, and government/special series; added TS/TG, OR/OD, LA and JK07/JK10 (Kargil/Leh before 2019) |
| `states.csv` | State vehicle counts (section 1), theft multipliers, camera-coverage share | Theft multipliers come from NCRB 2024 for Delhi, Tamil Nadu and Kerala, then tuned so the shares land near NCRB's; 1.0 elsewhere |
| `city_cameras.csv` | 606 city ANPR camera points in 40 cities | **Synthetic.** Camera IDs are invented; points are scattered around approximate city-centre coordinates |

## 4. Assumptions (not official figures)

- **Renewal behaviour.** Per-class propensity to renew and to come back after a lapse is tuned so the registry lands inside the official uninsured range. There is no public per-class figure for non-two-wheelers.
- **Vehicles leave the road without being de-registered.** Lifetime is log-normal; median 11 years for two-wheelers, 15 for cars, 5 for e-rickshaws. This is why the uninsured share is lower on the road (cameras) than in the registry.
- **Camera coverage.** Share of each state's fleet living in a city with ANPR cameras, capture rates per class, two-wheelers never read at toll plazas, and trips that pass several neighbouring plazas.
- **Read quality.** About 2.3% of reads have one swapped character (O/0, B/8, S/5, ...), 0.4% are partial, 0.25% unreadable, 0.26% double reads, and 1% arrive more than 24 hours late.
- **Insurer feed quirks.** 25% of first policies for vehicles registered since 2018 are filed under `NEW`. Each insurer formats plates its own way (United India drops the RTO zero-pad; Shriram pads Delhi codes). 0.4% of plates have typos.
- **Approximate catalogue.** Insurer weights are approximate motor-book size. Model launch dates are approximate to the month, so no model appears before it was sold. EV-share ramps by year are approximate.
- **Synthetic identifiers.** Chassis numbers use the real VIN layout and model-year codes, but the WMI is invented. Policy numbers, FIR numbers and RVSF certificate numbers are synthetic.
- **Names** come from regional pools, weighted roughly by Census-2011 state demographics. Any resemblance to a real person is coincidental.
- **Two pinned demo events** in the nightly-drop window: a Delhi two-wheeler (DL13SET1336) is reported stolen on 05-Nov and seen on camera on 06-Nov, and an open case is recovered on 06-Nov.
- **Not modelled yet:** the 4-Aug-2026 Supreme Court direction to lengthen new-vehicle third-party cover to 4 years (cars) and 6 years (two-wheelers). It had no announced effective date at the data cut-off.

## 5. Rebuilding `ref/`

`ref/build/map_tolls_to_states.py` and `ref/build/build_refs.py` regenerate the reference files from the
three public repos named in section 3 (`pip install pyshp` for the shapefile). Note that `states.csv` was
then hand-tuned: Delhi's theft multiplier was raised to 5.2 so Delhi's share of thefts lands near NCRB's.
