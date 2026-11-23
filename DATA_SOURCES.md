# Data sources

The records are simulated, because real per-vehicle registration and insurance data is not public in India. The generator (`generate_realistic_data.py`) is seeded, so it always writes the same files, and its main figures are set to match published ones. It also writes `calibration_report.md`, which compares the generated data with those figures.

## Published figures the data is matched to

| Measure | Generated | Published | Source |
|---|---:|---|---|
| Two-wheelers in the fleet | 73.4% | 74.7% (31 Mar 2020) | MoRTH Road Transport Year Book, via [Dataful](https://dataful.in/datasets/20224/) |
| Registered vehicles without valid third-party cover | 49.2% | over 44% (VAHAN, Mar 2026) to about 54–56% (Supreme Court, Aug 2026) | [Car Khabri](https://carkhabri.com/carblogs/44--vehicles-in-india-are-running-without-insurance), [The Law Advice](https://www.thelawadvice.com/news/sc-orders-automatic-e-challans-for-uninsured-vehicles-directs-4-year-insurance-for-new-cars-6-years-for-two-wheelers) |
| Vehicles stolen per year | 0.067% | about 0.06% (NCRB 2024) | [Kerala Kaumudi](https://keralakaumudi.com/en/india/general/one-vehicle-stolen-every-2.3-minutes-in-india-ncrb-data-shows-1790711) |
| Two-wheeler share of thefts | 83.2% | 85.4% (NCRB 2017) | [Factly](https://factly.in/ncrb-theft-data-up-to-2017) |
| Stolen vehicles recovered | 23.5% | about 15–25% (city police data) | [The Tribune](https://www.tribuneindia.com/news/chandigarh/3-vehicles-stolen-every-day-in-chandigarh-busy-markets-targeted/amp) |
| Vehicles per state | — | registered vehicles by state (2015) | MoSPI Statistical Year Book, via [Wikipedia](https://en.wikipedia.org/wiki/Indian_states_ranking_by_number_of_vehicles) |

## Real-world rules the data follows

- **Plates:** state code, RTO number, series and four digits. Delhi drops the RTO's leading zero and adds a class letter (`DL6SCP2349`). ([BankBazaar](https://www.bankbazaar.com/driving-licence/vehicle-number-plate.html))
- **BH-series plates** (`22 BH 1234 AA`) exist from 15 Sep 2021, for non-transport vehicles only. ([BankBazaar](https://www.bankbazaar.com/driving-licence/bharat-series-number-plates.html))
- **Old state codes stay valid:** Telangana plates use AP before 2014, TS until 14 Mar 2024 and TG after; Odisha moved from OR to OD. ([Telangana Today](https://telanganatoday.com/tg-series-for-new-vehicle-registration-from-friday))
- **Long-term third-party cover:** new vehicles sold from 1 Sep 2018 get 3 years (cars) or 5 years (two-wheelers). ([Mondaq](https://www.mondaq.com/india/insurance-laws-and-products/724138/long-term-motor-insurance-for-third-party-liability))
- **Insurer changes:** Bharti AXA General merged into ICICI Lombard on 8 Sep 2021, and Reliance General was renamed IndusInd General Insurance on 22 Sep 2025, so the feed has both names. ([AXA](https://axa.com/press/press-releases/axa-and-bharti-have-completed-the-combination-of-their-non-life-operations-in-india-into-icici-lombard), [BSE notice](https://rhnvrm.github.io/stock-market-circulars/circulars/bse/2025/bse-2025-10-23-e55e76ef566cb4a6-change-in-name-of-the-company-reliance-general-insurance-company-ltd))

## Reference data in `ref/`

| File | Contents | Origin |
|---|---|---|
| `toll_plazas.csv` | 701 NHAI toll plazas, with coordinates, and daily traffic where published | NHAI data via [geohacker/toll-plazas-india](https://github.com/geohacker/toll-plazas-india); states assigned with [datameet/maps](https://github.com/datameet/maps) |
| `rto_offices.csv` | 1,158 RTO codes, including the legacy ones above | [tpbadgujar/India-Codes](https://github.com/tpbadgujar/India-Codes), cleaned |
| `states.csv` | Vehicles per state, theft multipliers, camera coverage | The state table above, adjusted by hand |
| `city_cameras.csv` | 606 city camera points in 40 cities | Synthetic |
| `insurers.csv`, `vehicle_classes.csv` | The mappings the pipeline uses: insurer names, vehicle groups | Written for this project |

`ref/build/` has the two scripts that rebuild the reference files from those repositories (`pip install pyshp` for the map files).

## Assumptions

- **Renewals:** how often each vehicle class renews, or comes back after a lapse, is tuned so that the overall uninsured share lands in the published range. There is no public figure per class.
- **Vehicles leave the road without being de-registered** (median lifetime: 11 years for two-wheelers, 15 for cars). That is why a smaller share of the vehicles seen on camera is uninsured than in the registry.
- **Camera reads:** about 2.3% have one wrong character, 0.4% are partial, 0.25% are unreadable, 0.26% are double reads, and 1% arrive more than a day late.
- **Insurer feed:** 25% of first policies for vehicles registered since 2018 are filed under `NEW`, each insurer formats plates its own way, and 0.4% of plates have typos.
- **Identifiers and names are synthetic.** Chassis numbers follow the real format with an invented manufacturer code, and names come from regional name lists; any resemblance to a real person is coincidental.
- **Two fixed events** fall in the daily drops, for demos: a Delhi two-wheeler (`DL13SET1336`) reported stolen on 5 Nov and seen on camera on 6 Nov, and an open theft case recovered on 6 Nov.
