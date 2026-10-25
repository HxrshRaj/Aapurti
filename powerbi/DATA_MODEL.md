# Power BI data model (star schema)

> **Status:** the exports and `measures.dax` are produced by this repo and the CSVs are tested for shape. **No `.pbix` was built
> or opened, and the DAX has not been executed in Power BI.** Treat the measures as a starting point to verify in Desktop.
> All data is **synthetic**.

Files are written by `python -m aapurti.serving` (or `scripts/run_all.py`) into `powerbi/data/`.

## Tables

| Table | Grain | Role |
|---|---|---|
| `dim_date` | one row per calendar day | date dimension (mark as date table on `date`) |
| `dim_plant` | plant | dimension |
| `dim_sku` | SKU | dimension (`category`, `volume_class` = A/B/C, `supplier_id`) |
| `dim_supplier` | supplier | dimension (`lead_time_days`, `reliability`) |
| `dim_line` | production line | dimension (belongs to a plant) |
| `fact_daily_demand` | date x plant x SKU | units, promo flag |
| `fact_inventory_position` | plant x SKU, one snapshot (`as_of_date`) | on hand, avg daily demand, days of cover, safety stock, reorder point, risk |
| `fact_capacity_monthly` | month x line | available / run / downtime hours, utilization |
| `fact_forecast` | date x plant x SKU | last-28-day held-out forecast with actuals, plus next-28-day forecast (`is_future`) |
| `backtest_results` | volume class x model | MAPE / WAPE / RMSE / bias (standalone; not related to the star) |

## Relationships (all many-to-one, single direction from dimension to fact)

```
dim_date[date]        1 -> *  fact_daily_demand[demand_date]
dim_date[date]        1 -> *  fact_forecast[date]
dim_date[date]        1 -> *  fact_capacity_monthly[month_start]
dim_date[date]        1 -> *  fact_inventory_position[as_of_date]
dim_plant[plant_id]   1 -> *  fact_daily_demand[plant_id], fact_inventory_position[plant_id],
                              fact_forecast[plant_id], fact_capacity_monthly[plant_id]
dim_sku[sku_id]       1 -> *  fact_daily_demand[sku_id], fact_inventory_position[sku_id], fact_forecast[sku_id]
dim_line[line_id]     1 -> *  fact_capacity_monthly[line_id]
dim_supplier[supplier_id] 1 -> * dim_sku[supplier_id]      (snowflake; or merge into dim_sku in Power Query)
dim_plant[plant_id]   1 -> *  dim_line[plant_id]
```

`fact_inventory_position` has a single `as_of_date`, so time intelligence does not apply to it; use the date slicer only to
confirm the snapshot date.

## Business rules the measures follow (same as the pipeline and the Excel workbook)

* **Days of cover** = on hand / average daily demand over the trailing 28 days; blank when demand is 0.
* **Safety stock** = 1.65 x population std-dev of daily demand x sqrt(lead time days) (already computed in the table).
* **Stockout risk**: HIGH if days of cover < supplier lead time; MEDIUM if on hand < reorder point; else LOW.
* **Utilization** = run hours / available hours (ratio of sums).
* **WAPE** = sum |actual - forecast| / sum actual, over rows that have an actual.

## Build steps (Power BI Desktop)

See [README.md](README.md).
