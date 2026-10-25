# Approved reference values

Hand-computed expected values that the pipeline must reproduce. Everything here is **synthetic**.

| File | What it checks | How it is used |
|---|---|---|
| `approved_calculations.csv` | 14 single-formula cases (days of cover, safety stock, utilization, stockout risk), each with the arithmetic in `hand_working` | `tests/test_calcs_and_reference.py::test_approved_calculation_cases` compares `aapurti.calcs` |
| `fixture/` | a tiny hand-designed dataset (1 plant, 4 SKUs, 28 days, 1 line) including deliberately bad rows | `build_fixture.py` writes it; the Spark pipeline is run on it end to end |
| `fixture_expected.csv` | 31 expected gold / quarantine values for that fixture, with the working | `tests/test_calcs_and_reference.py::test_pipeline_matches_hand_computed_fixture` |

## Definitions (these are the "approved" rules)

* **On hand** = opening quantity + RECEIPTs - ISSUEs + signed ADJUSTMENTs, for movements dated on or before the as-of date
  (as-of = last demand date). Movements dated after as-of are excluded (the fixture contains one to prove it).
* **Average daily demand** = units over the trailing 28 days / 28 (missing days count as zero).
* **Demand sigma** = *population* standard deviation of daily units over those 28 days.
* **Days of cover** = on hand / average daily demand; null when average demand is 0.
* **Safety stock** = 1.65 x sigma x sqrt(lead time days). 1.65 is the z-value for a ~95% cycle service level.
* **Reorder point** = average daily demand x lead time + safety stock.
* **Stockout risk**: HIGH if days of cover < lead time; else MEDIUM if on hand < reorder point; else LOW (null cover => LOW).
* **Utilization** = sum(run hours) / sum(available hours) per line and month.

## Tolerance

Counts and on-hand quantities must match **exactly** (tolerance 0). Ratios and products that involve square roots or
division use an absolute tolerance of `1e-9` (`1e-12` for utilization), recorded per row in the `tolerance` column. This is far
tighter than the rounding in the hand arithmetic, and it is there only to absorb floating-point representation error.

## Worked example (SKU `SB`)

Demand alternates 8, 12 for 28 days (mean 10, population sigma 2). Opening 100, receipt 200, issues 280 => on hand 20.
Days of cover = 20 / 10 = 2. Lead time 4 days. Safety stock = 1.65 x 2 x sqrt(4) = 6.6. Reorder point = 10 x 4 + 6.6 = 46.6.
Cover 2 < lead time 4 => **HIGH**.
