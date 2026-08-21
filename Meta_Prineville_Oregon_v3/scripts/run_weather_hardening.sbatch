#!/bin/bash
#SBATCH -J prineville_weather_hard
#SBATCH -p sched_mit_sloan_batch_r8
#SBATCH -t 04:00:00
#SBATCH -c 8
#SBATCH --mem=32G
#SBATCH -o /home/nacevedo/RA/data-center-externalities-modeling/Meta_Prineville_Oregon_v3/outputs/slurm_logs/weather_hardening_%j.out
#SBATCH -e /home/nacevedo/RA/data-center-externalities-modeling/Meta_Prineville_Oregon_v3/outputs/slurm_logs/weather_hardening_%j.err

set -eo pipefail
unset PYTHONPATH PYTHONHOME
export PYTHONNOUSERSITE=1
export OMP_NUM_THREADS=4
export MKL_NUM_THREADS=4
export OPENBLAS_NUM_THREADS=4
export PATH="/home/nacevedo/.conda/envs/dc_externalities/bin:${PATH}"
PY="/home/nacevedo/.conda/envs/dc_externalities/bin/python"
ROOT="/home/nacevedo/RA/data-center-externalities-modeling/Meta_Prineville_Oregon_v3"
cd "${ROOT}"
mkdir -p outputs/slurm_logs outputs/pipeline_report

echo "host=$(hostname) partition=${SLURM_JOB_PARTITION} job=${SLURM_JOB_ID} node=${SLURM_NODELIST}"
echo "start=$(date -Is)"
"${PY}" --version
"${PY}" -c "import sys; print(sys.executable)"

echo "=== BEFORE water-model snapshot (reference, not a target) ==="
"${PY}" - <<'PY'
from pathlib import Path
import pandas as pd
root = Path("/home/nacevedo/RA/data-center-externalities-modeling/Meta_Prineville_Oregon_v3")
wm = pd.read_csv(root / "outputs/conditional_water_model.csv").iloc[0]
ann = pd.read_csv(root / "outputs/conditional_annual_compare.csv")
base = pd.read_csv(root / "outputs/pipeline_report/water_holdout_baseline_compare.csv")
stoch = pd.read_csv(root / "outputs/stochastic_proxy_water_model_diagnostics.csv")
hold = ann[ann.split.eq("holdout")]
print("BEFORE_cond_kind", wm["kind"])
print("BEFORE_cond_scale", wm["scale"])
print("BEFORE_cond_bic", wm["bic"])
print("BEFORE_err_2023", float(hold.loc[hold.year.eq(2023), "water_pct_error"].iloc[0]))
print("BEFORE_err_2024", float(hold.loc[hold.year.eq(2024), "water_pct_error"].iloc[0]))
h = hold.dropna(subset=["water_pct_error"])
print("BEFORE_cond_mape", float(h.water_pct_error.abs().mean()))
print("BEFORE_training_mean_mape", float(base.loc[base.predictor.eq("training_mean"), "MAPE_pct"].iloc[0]))
print("BEFORE_stoch_selected", stoch.loc[stoch.selected.astype(str).str.lower().eq("true"), "model"].iloc[0])
print("BEFORE_stoch_train_score", float(stoch.loc[stoch.selected.astype(str).str.lower().eq("true"), "rolling_one_step_mape_pct"].iloc[0]))
print(base.to_string(index=False))
PY

echo "=== KBDN download + weather rebuild ==="
"${PY}" src/prepare_weather.py
"${PY}" src/prepare_weather_kbdn.py
"${PY}" src/prepare_weather_ks39.py

echo "=== post-weather required-driver check ==="
"${PY}" - <<'PY'
from pathlib import Path
import numpy as np
import pandas as pd
root = Path("/home/nacevedo/RA/data-center-externalities-modeling/Meta_Prineville_Oregon_v3")
w = pd.read_csv(root / "data/processed/weather_hourly.csv")
req = ["t_db_C", "t_wb_C", "rh_pct", "pressure_Pa"]
x = w[req].apply(pd.to_numeric, errors="coerce")
bad = ~np.isfinite(x.to_numpy(dtype=float)).all(axis=1)
print("n_hours", len(w), "n_bad_any_required", int(bad.sum()))
a = pd.read_csv(root / "outputs/pipeline_report/weather_finite_driver_audit.csv")
print("audit_rows", len(a))
print("audit_unresolved", int(pd.to_numeric(a.get("post_resolution_finite", 1), errors="coerce").fillna(1).eq(0).sum()) if len(a) else 0)
print(a["resolution_method"].astype(str).value_counts().to_string() if len(a) else "empty")
print("weather_source_counts")
print(w["weather_source"].astype(str).value_counts().to_string())
if int(bad.sum()):
    raise SystemExit("BLOCKED: unresolved required weather drivers")
PY

echo "=== conditional ==="
"${PY}" run_prineville.py conditional

echo "=== simulate ==="
"${PY}" run_prineville.py simulate

echo "=== report (non-LaTeX) ==="
"${PY}" run_prineville.py report

echo "=== AFTER water-model snapshot ==="
"${PY}" - <<'PY'
from pathlib import Path
import pandas as pd
root = Path("/home/nacevedo/RA/data-center-externalities-modeling/Meta_Prineville_Oregon_v3")
wm = pd.read_csv(root / "outputs/conditional_water_model.csv").iloc[0]
ann = pd.read_csv(root / "outputs/conditional_annual_compare.csv")
base = pd.read_csv(root / "outputs/pipeline_report/water_holdout_baseline_compare.csv")
stoch = pd.read_csv(root / "outputs/stochastic_proxy_water_model_diagnostics.csv")
hold = ann[ann.split.eq("holdout")]
print("AFTER_cond_kind", wm["kind"])
print("AFTER_cond_scale", wm["scale"])
print("AFTER_cond_bic", wm["bic"])
print("AFTER_err_2023", float(hold.loc[hold.year.eq(2023), "water_pct_error"].iloc[0]))
print("AFTER_err_2024", float(hold.loc[hold.year.eq(2024), "water_pct_error"].iloc[0]))
h = hold.dropna(subset=["water_pct_error"])
print("AFTER_cond_mape", float(h.water_pct_error.abs().mean()))
print("AFTER_scorecard")
print(pd.read_csv(root / "outputs/pipeline_report/validation_scorecard.csv").to_string(index=False))
print("AFTER_baselines")
print(base.to_string(index=False))
print("AFTER_stoch")
print(stoch.to_string(index=False))
cons = pd.read_csv(root / "outputs/pipeline_report/report_consistency_audit.csv")
print("consistency_fail", int(cons.status.eq("FAIL").sum()) if "status" in cons.columns else cons.head())
print("result_claims", len(pd.read_csv(root / "outputs/pipeline_report/result_claims.csv")))
PY

echo "=== focused tests ==="
"${PY}" -m pytest tests/test_weather_ks39.py tests/test_graybox.py tests/test_conditional_reconstruction.py tests/test_documentary_evidence.py tests/test_prn1_permit_evidence.py tests/test_pipeline_report.py -q --tb=short

echo "=== full project pytest ==="
"${PY}" -m pytest -q --tb=short

echo "=== audit ==="
"${PY}" run_prineville.py audit

echo "end=$(date -Is)"
