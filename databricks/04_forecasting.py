# Databricks notebook source
# MAGIC %md
# MAGIC # Forecasting: rolling-origin backtest (naive, seasonal naive, moving average, Holt-Winters, gradient boosting)
# MAGIC Runs on the driver with pandas/statsmodels/scikit-learn (the series are small). Needs `%pip install statsmodels scikit-learn`.

# COMMAND ----------

# MAGIC %pip install statsmodels scikit-learn pyarrow

# COMMAND ----------

# MAGIC %run ./00_setup

# COMMAND ----------

from aapurti.forecasting.backtest import final_forecasts, make_origins, prepare_panel, run_forecasts, score, select_winners

# gold tables are read through Spark so this works for Delta paths too, then collected to pandas
daily = spark.read.format(FMT).load(f"{LAKE}/gold/daily_demand").toPandas()  # noqa: F821
panel = prepare_panel(daily)
preds = run_forecasts(panel, make_origins(panel["date"].max()))
results = score(preds, panel)
winners = select_winners(results)
fva = final_forecasts(panel, preds, winners)

for name, pdf in {"backtest_results": results, "model_selection": winners, "forecast_vs_actual": fva}.items():
    spark.createDataFrame(pdf).write.mode("overwrite").format(FMT).save(f"{LAKE}/gold/{name}")  # noqa: F821
display(spark.createDataFrame(results))  # noqa: F821
