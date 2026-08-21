#!/bin/bash
#SBATCH -J prn_wx_audit
#SBATCH -p sched_mit_sloan_batch_r8
#SBATCH -t 00:20:00
#SBATCH -c 2
#SBATCH --mem=8G
#SBATCH -o /home/nacevedo/RA/data-center-externalities-modeling/Meta_Prineville_Oregon_v3/outputs/slurm_logs/weather_auditfix_%j.out
#SBATCH -e /home/nacevedo/RA/data-center-externalities-modeling/Meta_Prineville_Oregon_v3/outputs/slurm_logs/weather_auditfix_%j.err

set -eo pipefail
unset PYTHONPATH PYTHONHOME
export PYTHONNOUSERSITE=1
export PATH="/home/nacevedo/.conda/envs/dc_externalities/bin:${PATH}"
PY="/home/nacevedo/.conda/envs/dc_externalities/bin/python"
ROOT="/home/nacevedo/RA/data-center-externalities-modeling/Meta_Prineville_Oregon_v3"
cd "${ROOT}"

"${PY}" - <<'PY'
from pathlib import Path
import sys
sys.path.insert(0, "src")
from pipeline_report_results import weather_driver_audit
from pipeline_report_diagrams import render_source_tree_png

root = Path(".")
audit = weather_driver_audit()
audit.to_csv(root / "outputs/pipeline_report/weather_finite_driver_audit.csv", index=False)
audit.to_csv(root / "outputs/weather_ks39/weather_finite_driver_audit.csv", index=False)
print("audit_rows", len(audit))
print("tertiary_ids", sorted(set(audit.tertiary_source.astype(str))) if "tertiary_source" in audit.columns else None)
print("unresolved", int((audit.post_resolution_finite == 0).sum()) if "post_resolution_finite" in audit.columns else None)
png = render_source_tree_png(root / "outputs/pipeline_report/data_source_tree.png")
print("wrote", png)
PY
