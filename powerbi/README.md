# Building the report in Power BI Desktop

**Not built here.** This folder contains everything needed to build the report, but no `.pbix` was created or verified in this
repository, and Power BI was not used. The steps below are instructions, not a record of something that was run.

## 1. Load the data

1. Power BI Desktop > **Get data > Text/CSV**. Load every file in [`data/`](data) (`dim_*.csv`, `fact_*.csv`, `backtest_results.csv`).
   (Alternatively use *Get data > Folder* and combine, or load the Parquet gold tables from `data/lake/gold/` with the Parquet connector
   after running the pipeline.)
2. In Power Query set types: dates (`dim_date[date]`, `fact_daily_demand[demand_date]`, `fact_forecast[date]`,
   `fact_inventory_position[as_of_date]`, `fact_capacity_monthly[month_start]`) as **Date**; `fact_forecast[is_future]` as **True/False**;
   numeric columns as **Decimal Number**.

## 2. Model

1. **Model view**: create the relationships listed in [DATA_MODEL.md](DATA_MODEL.md) (dimension -> fact, many-to-one, single direction).
2. Select `dim_date` > **Mark as date table** > `date`.
3. Hide the foreign-key columns on the fact tables; keep the dimension attributes visible.

## 3. Measures

1. Create a table called `_Measures` (Home > Enter data, one blank column) to hold the measures.
2. Copy each measure from [`measures.dax`](measures.dax) into `_Measures` (Modeling > New measure).
3. Format: `Forecast WAPE`, `Forecast Accuracy`, `Utilization`, `Stockout Risk %`, `Units YoY %` as percentage; `Days of Cover` as decimal (1 dp).

## 4. Report pages

| Page | Visuals |
|---|---|
| Overview | Cards: `Forecast Accuracy`, `High Risk SKUs`, `Days of Cover`, `Utilization`. Slicers: `dim_plant[plant_name]`, `dim_sku[category]`, `dim_sku[volume_class]`. |
| Forecast | Line chart: axis `dim_date[date]`, values `Actual Units (held-out)` and `Forecast Units`. Table: `dim_sku[sku_id]`, `Forecast WAPE`, `Forecast Bias %`. Column chart from `backtest_results`: `model` vs `wape` per `volume_class`. |
| Inventory | Table of `fact_inventory_position` rows (sku, plant, on hand, `Days of Cover (SKU)`, reorder point, `stockout_risk`) with conditional formatting on `stockout_risk`; card `Inventory Value`. |
| Capacity | Clustered bar: `dim_line[line_id]` vs `Utilization`; line chart by `dim_date` month; constant line at 90%. |
| Demand | Line chart `Total Units` vs `Units LY` by month; card `Units YoY %`. |

## 5. Check the numbers before you trust the report

The same business rules are implemented in Spark, in `src/aapurti/calcs.py` and in the Excel export. After building:

* `Days of Cover (SKU)` for a SKU should equal the `days_of_cover` column in `fact_inventory_position.csv` for that row.
* `Utilization` for a line-month should equal `fact_capacity_monthly[utilization]`.
* The grand total of `Total Units` should equal `reports/reconciliation.md` "demand units (total)" pipeline column.

If a measure disagrees with those, the DAX (not the pipeline) is the thing to debug: the pipeline values are checked against hand-computed
references in `reference/`.
