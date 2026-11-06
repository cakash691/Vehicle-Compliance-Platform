# Calibration report

Generated with `--vehicles 100000 --seed 42`. Measured on the simulated ground truth as of 2026-11-06.

## Fleet composition (registry)

| Class | Share here | Official | Source |
|---|---:|---:|---|
| Two-wheelers | 73.4% | 74.7% | MoRTH, as on 31-03-2020 |
| Cars, jeeps & taxis | 13.8% | 13.4% | MoRTH, as on 31-03-2020 |
| Goods vehicles | 4.4% | 4.4% | MoRTH, as on 31-03-2020 |
| Buses | 0.7% | 0.7% | MoRTH, as on 31-03-2020 |
| Others (3W, e-rickshaw, tractor) | 7.6% | 6.9% | MoRTH, as on 31-03-2020 |

## Uninsured share (no valid third-party cover on the as-of date)

| Class | Registered | Uninsured (registry) | Seen on road (90d) | Uninsured (on road) | Official anchor |
|---|---:|---:|---:|---:|---|
| 2W | 72,990 | 53.9% | 18,216 | 37.5% | 66% in 2019-20 (IIB); lower now that 5-yr TP covers 2018+ bikes |
| CAR | 12,764 | 26.2% | 6,205 | 13.8% |  |
| TAXI | 993 | 38.2% | 541 | 7.8% |  |
| LCV | 2,464 | 33.2% | 1,235 | 13.0% |  |
| TRUCK | 1,962 | 27.1% | 1,302 | 10.6% |  |
| BUS | 704 | 26.1% | 473 | 8.9% |  |
| 3W_P | 3,705 | 51.2% | 1,405 | 23.3% |  |
| 3W_G | 952 | 48.2% | 292 | 22.6% |  |
| ERICK | 810 | 66.2% | 263 | 51.0% |  |
| TRACTOR | 2,163 | 68.1% | 381 | 69.6% |  |
| Non-two-wheelers | 26,517 | 36.3% | 12,097 | 16.8% | ~30% in 2019-20 (back-solved from IIB 57% overall, 66% of 2W, 75% 2W share) |
| **All** | 99,507 | **49.2%** | 30,313 | **29.2%** | 44% (VAHAN, Mar-2026) to 54-56% (Supreme Court, Aug-2026) |

Official anchors for the registry figure: >44% uninsured (VAHAN data as of 6-Mar-2026, shared in the Rajya Sabha) and ~54-56% (16.54 crore of 30.48 crore vehicles, recorded by the Supreme Court on 4-Aug-2026); IIB: 66% of two-wheelers (2019-20). The on-road share is lower because vehicles that have left the road (but were never de-registered) are mostly the uninsured ones.

- Two-wheelers whose first policy was not renewed within 30 days of expiry: 67.4% (IIB: about 52% of vehicles do not renew after the first year, mostly two-wheelers).

## Theft

- Theft FIRs 2019-2026: 524 -> 0.067% of registered vehicles per year (NCRB 2024: ~2.3 lakh thefts / ~40 crore vehicles = ~0.06%).
- Two-wheeler share of thefts: 83.2% (NCRB 2017: 85.4% motorcycles/scooters).
- Delhi share of thefts: 20.2% (NCRB 2024: 40,139 of ~2.3 lakh = ~17.5%).
- Recovered: 23.5% (city police data: ~15-25%).
- Scrapped at RVSFs (SHREDDED): 92 vehicles (56 government vehicles >15 years).

## ANPR captures

- Rows: 459,166 over 365 days from 1,307 cameras (123,672 toll / 335,494 city).
- Distinct registered vehicles seen: 49,196 of 100,000.
- Read errors: OCR swaps 2.29%, partial 0.41%, unreadable 0.25%; duplicate lane reads 0.26%.
- Late arrivals (ingested >24h after capture): 0.98%.
- Stolen vehicles caught on camera (original plate): 28; cloned plates of scrapped vehicles: 7; fake plates: 686 reads.

| ANPR vehicle_type | Rows |
|---|---:|
| Two-Wheeler | 195,487 |
| Truck | 60,618 |
| Hatchback | 49,890 |
| SUV/MUV | 45,309 |
| Three-Wheeler | 35,402 |
| Sedan | 25,530 |
| LCV | 21,143 |
| Bus | 16,810 |
| E-Rickshaw | 5,189 |
| Van | 2,038 |
| Tractor | 1,750 |

