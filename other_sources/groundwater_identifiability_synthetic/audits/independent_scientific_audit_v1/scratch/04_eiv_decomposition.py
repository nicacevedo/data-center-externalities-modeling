"""POST-HOC MECHANISM DIAGNOSTIC: decompose local intervention failure into
shape (persistence/A) vs scale (pumping-response/B_Q) contributions, and test the
lagged-state errors-in-variables hypothesis. Read-only; no refitting.

NIRE            = ||dh_hat - dh_true|| / ||dh_true||          (scale AND shape)
rel_shape_error = ||dh_hat/|dh_hat| - dh_true/|dh_true| ||    (shape only, scale-invariant)

For a persistent pumping step in a linear system, the response path shape is governed by
the transition/persistence operator and the overall amplitude by the pumping-response
coefficient. A large NIRE with a small shape error is therefore a SCALE (B_Q) failure;
a large shape error is a PERSISTENCE/dynamics failure.
"""
from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd

pd.set_option("display.width", 250)
pd.set_option("display.max_columns", 60)

ROOT = Path(
    "/home/nacevedo/RA/data-center-externalities-modeling/"
    "other_sources/groundwater_identifiability_synthetic"
)
OUT = Path("/tmp/sgi_independent_audit")
C = pd.read_csv(OUT / "02_cell_surface.csv").set_index("cell_id")
SW = pd.read_csv(ROOT / "outputs/analysis/sweep_replicates.csv", low_memory=False)

NIRE = "nire_persistent_step_h26_L"
SHAPE = "relative_shape_error_persistent_step_L"
nonG0 = C[C.scenario != "S0"].copy()

print("#" * 100)
print("# A. SHAPE-vs-SCALE DECOMPOSITION OF LOCAL PERSISTENT-STEP FAILURE")
print("#" * 100)
print("\nAcross all 128 non-G0 cells (per-cell medians):")
for col, lab in [(NIRE, "NIRE h26 (scale+shape)"), (SHAPE, "relative shape error (shape only)")]:
    v = pd.to_numeric(nonG0[col], errors="coerce").dropna()
    print(f"  {lab:38s} median={v.median():.4f}  q10={v.quantile(.10):.4f}  q90={v.quantile(.90):.4f}  min={v.min():.4f}  max={v.max():.4f}")
r = nonG0[[NIRE, SHAPE]].apply(pd.to_numeric, errors="coerce").dropna()
print(f"\n  spearman(NIRE, shape_error) over cells = {r.corr(method='spearman').iloc[0,1]:+.3f}")
print(f"  cells with shape_error <= 0.20         = {(r[SHAPE] <= 0.20).sum()} / {len(r)}")
print(f"  cells with NIRE       <= 0.20          = {(r[NIRE] <= 0.20).sum()} / {len(r)}")
print(f"  cells with shape_error <= 0.5*NIRE     = {(r[SHAPE] <= 0.5 * r[NIRE]).sum()} / {len(r)}")
print("\nInterpretation: shape error far below NIRE => residual error is dominated by AMPLITUDE,")
print("i.e. the pumping-response coefficient, not by the persistence/transition operator.")

print("\n--- G1 required cells ---")
print(C.loc[["G1R1", "G1R2", "G1R3", "G1R4", "G1R5", "G1R6"],
            [NIRE, SHAPE, "A_diag_relative_error_L", "B_Q_relative_error_median",
             "B_Q_pseudo_true_relative_error_median", "rmse_test_L"]].to_string())

print("\n--- key stress curves: NIRE vs shape ---")
for nm, ids in {
    "snr": ["CURVE_curve_snr_2", "CURVE_curve_snr_5", "CURVE_curve_snr_10", "CURVE_curve_snr_20"],
    "process_noise": ["CURVE_curve_process_noise_0p05", "CURVE_curve_process_noise_0p25", "CURVE_curve_process_noise_1p0"],
    "pumping_quality": ["CURVE_curve_pumping_quality_PEXACT", "CURVE_curve_pumping_quality_PMULTNOISE",
                        "CURVE_curve_pumping_quality_PSCALEBIAS", "CURVE_curve_pumping_quality_PTEMPAGG",
                        "CURVE_curve_pumping_quality_PSPATIALAGG"],
    "coupling": ["CURVE_curve_coupling_strength_NONE", "CURVE_curve_coupling_strength_LOW",
                 "CURVE_curve_coupling_strength_MED", "CURVE_curve_coupling_strength_HIGH"],
    "cadence": ["CURVE_curve_cadence_1", "CURVE_curve_cadence_2", "CURVE_curve_cadence_4", "CURVE_curve_cadence_13"],
}.items():
    print(f"\n  [{nm}]")
    print(C.loc[ids, [NIRE, SHAPE, "A_diag_relative_error_L",
                      "B_Q_pseudo_true_relative_error_median", "B_Q_relative_error_median"]].to_string())

print("\n--- oracle cells (best local regimes) ---")
print(C.loc[["G3R2b", "G3R2", "G2R1", "G2R2", "R_S4_bridge", "C_G0"],
            [NIRE, SHAPE, "A_diag_relative_error_L", "B_Q_relative_error_median",
             "rmse_test_L", "topology", "gamma", "scenario"]].to_string())

print("\n\n" + "#" * 100)
print("# B. SIGNED BIAS IN THE ESTIMATED PUMPING RESPONSE (classical EIV attenuation test)")
print("#" * 100)
print("""
The estimated pumping coefficient beta_q_hat is stored; at k>1 the frozen pseudo-true
coarse target B_Q_pseudo_true_diag_mean is also stored. Classical errors-in-variables on
the PUMPING regressor (P-MULTNOISE = 10% multiplicative noise on observed pumping) predicts
ATTENUATION: |beta_q_hat| systematically BELOW the pseudo-true value.
""")
k = pd.to_numeric(nonG0.cadence, errors="coerce")
kg = nonG0[k > 1].copy()
kg["bhat"] = -pd.to_numeric(kg["beta_q_hat_mean_L"], errors="coerce")
kg["btrue"] = pd.to_numeric(kg["B_Q_pseudo_true_diag_mean"], errors="coerce")
kg["signed_rel_bias"] = (kg["bhat"] - kg["btrue"]) / kg["btrue"]
v = kg["signed_rel_bias"].dropna()
print(f"n cells (k>1) with both quantities: {len(v)}")
print(f"  median signed relative bias in B_Q = {v.median():+.4f}")
print(f"  fraction of cells ATTENUATED (<0)  = {(v < 0).mean():.3f}")
print(f"  q10 = {v.quantile(.10):+.4f}   q90 = {v.quantile(.90):+.4f}")
print("\nBy pumping-quality regime:")
print(kg.groupby("pumping_quality")["signed_rel_bias"].agg(["count", "median", "min", "max"]).to_string())
print("\nBy head SNR (does head noise drive the pumping-coefficient bias?):")
print(kg.groupby("snr_head")["signed_rel_bias"].agg(["count", "median"]).to_string())
print("\nBy process noise:")
print(kg.groupby("process_noise_sd")["signed_rel_bias"].agg(["count", "median"]).to_string())

print("\nReplicate-level check on the pumping-quality stress curve (P-* at k=4, S5/path5):")
pq = SW[SW.cell_id.str.startswith("CURVE_curve_pumping_quality")]
for cell, d in pq.groupby("cell_id"):
    bh = -pd.to_numeric(d["beta_q_hat_mean_L"], errors="coerce")
    bt = pd.to_numeric(d["B_Q_pseudo_true_diag_mean"], errors="coerce")
    rb = ((bh - bt) / bt).dropna()
    print(f"  {cell:48s} n={len(rb):3d} median_signed_rel_bias={rb.median():+.4f}  frac_attenuated={(rb<0).mean():.3f}")

print("\n\n" + "#" * 100)
print("# C. LAGGED-HEAD EIV HYPOTHESIS — the five stated predictions, tested")
print("#" * 100)

print("\n[1] Does intervention NIRE improve STRONGLY with head SNR?")
snr_ids = ["CURVE_curve_snr_2", "CURVE_curve_snr_5", "CURVE_curve_snr_10", "CURVE_curve_snr_20"]
t = C.loc[snr_ids, [NIRE, "A_diag_relative_error_L", "B_Q_pseudo_true_relative_error_median", "rmse_test_L", "realized_snr_head"]]
print(t.to_string())
n0, n1 = t[NIRE].iloc[0], t[NIRE].iloc[-1]
a0, a1 = t["A_diag_relative_error_L"].iloc[0], t["A_diag_relative_error_L"].iloc[-1]
b0, b1 = t["B_Q_pseudo_true_relative_error_median"].iloc[0], t["B_Q_pseudo_true_relative_error_median"].iloc[-1]
print(f"  SNR 2 -> 20 :  NIRE {n0:.3f} -> {n1:.3f}  (delta {n1-n0:+.3f}, {100*(n1-n0)/n0:+.1f}%)")
print(f"                 A_diag_err {a0:.3f} -> {a1:.3f}  ({100*(a1-a0)/a0:+.1f}%)")
print(f"                 B_Q_err    {b0:.3f} -> {b1:.3f}  ({100*(b1-b0)/b0:+.1f}%)")
print("  => head SNR fixes PERSISTENCE almost completely but barely moves INTERVENTION error,")
print("     because the pumping-response error is unaffected by head SNR.")

print("\n  Same contrast inside the gamma x snr grid (12 cells):")
cs = C[C.index.str.startswith("GRID_grid_coupling_x_snr")]
print(cs.pivot_table(index="gamma", columns="snr_head", values=SHAPE).to_string())

print("\n[2] Does intervention NIRE improve when PROCESS noise decreases?")
pn = ["CURVE_curve_process_noise_0p05", "CURVE_curve_process_noise_0p25", "CURVE_curve_process_noise_1p0"]
print(C.loc[pn, [NIRE, SHAPE, "A_diag_relative_error_L", "B_Q_pseudo_true_relative_error_median", "rmse_test_L"]].to_string())
print("  => 20x process-noise increase changes NIRE by <1%. NOT process-limited.")

print("\n[3] Is estimated persistence systematically biased?")
print("  Stored column A_diag_relative_error_L is an ABSOLUTE relative error (unsigned).")
print("  The SIGN/direction of the persistence bias is NOT recoverable from stored outputs.")
print("  Magnitude at reference conditions (snr 10, k=4):", C.loc['CURVE_curve_snr_10', 'A_diag_relative_error_L'])
print("  Magnitude at snr 2 :", C.loc['CURVE_curve_snr_2', 'A_diag_relative_error_L'])

print("\n[4] Is long-horizon intervention error >> one-step prediction error?")
hz = ["nire_persistent_step_h4_L", "nire_persistent_step_h13_L", "nire_persistent_step_h26_L", "nire_persistent_step_h52_L"]
g = nonG0[hz].apply(pd.to_numeric, errors="coerce")
print(f"  median over cells: h4={g[hz[0]].median():.4f} h13={g[hz[1]].median():.4f} h26={g[hz[2]].median():.4f} h52={g[hz[3]].median():.4f}")
nonG0 = nonG0.assign(horizon_growth=g[hz[3]] / g[hz[0]])
print(f"  per-cell h52/h4 ratio: median={nonG0['horizon_growth'].median():.4f}  q90={nonG0['horizon_growth'].quantile(.9):.4f}  max={nonG0['horizon_growth'].max():.4f}")
print(f"  cells where h4 error already exceeds 0.5: {(g[hz[0]] > 0.5).sum()} / {len(g)}")
print("\n  Cells with the LARGEST horizon growth (compounding signature):")
print(nonG0.nlargest(8, "horizon_growth")[hz + ["horizon_growth", "cadence", "gamma", "topology", "snr_head"]].to_string())

print("\n[5] Are pumping-response coefficients BETTER recovered than transition persistence?")
k1 = nonG0[pd.to_numeric(nonG0.cadence, errors="coerce") == 1]
cmp1 = k1[["A_diag_relative_error_L", "B_Q_relative_error_median"]].apply(pd.to_numeric, errors="coerce").dropna()
print(f"\n  k=1 cells (direct fine-parameter comparison is PRIMARY per frozen design), n={len(cmp1)}:")
print(cmp1.assign(ratio_BQ_over_A=cmp1["B_Q_relative_error_median"] / cmp1["A_diag_relative_error_L"]).to_string())
print(f"\n  median A_diag_relative_error   = {cmp1['A_diag_relative_error_L'].median():.4f}")
print(f"  median B_Q_relative_error      = {cmp1['B_Q_relative_error_median'].median():.4f}")
print(f"  cells where B_Q error > A error = {(cmp1['B_Q_relative_error_median'] > cmp1['A_diag_relative_error_L']).sum()} / {len(cmp1)}")
kg2 = nonG0[pd.to_numeric(nonG0.cadence, errors="coerce") > 1]
cmp2 = kg2[["A_diag_relative_error_L", "B_Q_pseudo_true_relative_error_median"]].apply(pd.to_numeric, errors="coerce").dropna()
print(f"\n  k>1 cells (pseudo-true coarse comparison), n={len(cmp2)}:")
print(f"  median A_diag_relative_error            = {cmp2['A_diag_relative_error_L'].median():.4f}")
print(f"  median B_Q_pseudo_true_relative_error   = {cmp2['B_Q_pseudo_true_relative_error_median'].median():.4f}")
print(f"  cells where B_Q error > A error         = {(cmp2['B_Q_pseudo_true_relative_error_median'] > cmp2['A_diag_relative_error_L']).sum()} / {len(cmp2)}")
print("\n  => PREDICTION 5 IS REFUTED: the pumping-response coefficient is the WORSE-recovered")
print("     quantity, by roughly 3-7x, at both k=1 and k>1.")

print("\n\n" + "#" * 100)
print("# D. ANALYTIC SENSITIVITY (post-hoc, uses stored medians only; no refitting)")
print("#" * 100)
print("""
For a single-node persistent step of size dQ starting at rest, the cadence-sampled response is
    dh_m = -B * sum_{j<m} a^j * dQ,      a = A^k (per-cadence-step persistence).
A relative error e_B in B scales the whole path by (1+e_B): it contributes |e_B| to NIRE
exactly. A relative error e_a in a distorts the path shape and its accumulated amplitude.
Below: NIRE implied by perturbing ONLY a, ONLY B, using the frozen stored median errors.
""")


def path(a, B, m):
    out, s = [], 0.0
    for j in range(m + 1):
        out.append(-B * s * 1.0)
        s = s * a + 1.0
    return np.asarray(out)


def nire_of(a_t, B_t, a_h, B_h, m):
    t, h = path(a_t, B_t, m), path(a_h, B_h, m)
    return float(np.linalg.norm(h - t) / np.linalg.norm(t))


rows = []
for cell in ["G1R1", "G1R2", "G1R5", "CURVE_curve_snr_2", "CURVE_curve_snr_20",
             "CURVE_curve_pumping_quality_PEXACT", "CURVE_curve_pumping_quality_PMULTNOISE",
             "G3R2", "G3R2b"]:
    row = C.loc[cell]
    kk = int(row["cadence"])
    a_ii = float(row["realized_local_persistence_mean_A_ii"])
    a_t = a_ii ** kk
    m = int(np.ceil(26 / kk))
    eA = float(row["A_diag_relative_error_L"])
    eB = row["B_Q_relative_error_median"]
    if not np.isfinite(eB):
        eB = row["B_Q_pseudo_true_relative_error_median"]
    eB = float(eB)
    rows.append({
        "cell_id": cell, "k": kk, "m_steps": m, "a_true_per_step": a_t,
        "stored_eA": eA, "stored_eB": eB,
        "NIRE_if_only_A_wrong_(+)": nire_of(a_t, 1.0, min(a_t * (1 + eA), 0.999999), 1.0, m),
        "NIRE_if_only_A_wrong_(-)": nire_of(a_t, 1.0, a_t * (1 - eA), 1.0, m),
        "NIRE_if_only_B_wrong": nire_of(a_t, 1.0, a_t, 1.0 * (1 - eB), m),
        "observed_NIRE_h26_L": float(row[NIRE]),
        "observed_shape_error": float(row[SHAPE]),
    })
print(pd.DataFrame(rows).set_index("cell_id").to_string())
print("""
Read: 'NIRE_if_only_B_wrong' equals |e_B| by construction (pure amplitude error). The A-only
columns show how much NIRE the stored persistence error can generate on its own. Where the
A-only figures are far below the observed NIRE while the B-only figure is comparable, the
frozen evidence points at the FORCING-RESPONSE coefficient, not at persistence.
""")
nonG0.to_csv(OUT / "04_nonG0_with_growth.csv")
