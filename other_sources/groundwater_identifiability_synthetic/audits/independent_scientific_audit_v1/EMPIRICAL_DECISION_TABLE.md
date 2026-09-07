# Empirical decision table (POST-HOC; frozen gates unchanged)

Derived read-only from `outputs/analysis/sweep_replicates.csv` at
DESIGN_HASH `b53f5594…a8a5`, CODE_HASH `7cc64809…d863c`, 7,740 ANALYSIS replicates.

Classification uses ONLY frozen criteria: the G1 intervention threshold 0.20 on
`median(nire_persistent_step_h26_L)`, the G2 edge criterion 0.80 on
`median(strong_edge_undirected_f1)`, the G3 falsification outcome (hard failure,
network NOT_EARNED globally), and the frozen `absolute_S_identifiable` flag.
No new thresholds are introduced.

## Tallies

| label | cells |
|---|---|
| `FORECASTING_ONLY` | 126 |
| `ABSOLUTE_PHYSICAL_SCALE_NOT_IDENTIFIED` | 125 |
| `NETWORK_NOT_EARNED` | 122 |
| `SPATIAL_FORCING_DIAGNOSTIC_ONLY` | 17 |
| `NETWORK_CONDITIONALLY_TESTABLE` | 7 |
| `LOCAL_RESPONSE_CREDIBLE` | 3 |

## Regimes meeting the frozen local criterion

| cell | scenario | topology | true coupling | k | pumping | recharge | rho | MCAR | SNR | proc noise | NIRE_L |
|---|---|---|---|---|---|---|---|---|---|---|---|
| C_G0 | S0 | single | n/a (single node) | 1 | P-EXACT | R-EXACT | 0.0 | 0.0 | inf | 0.0 | 0.0000 |
| G3R2 | S6a | null5 | gamma=HIGH but C_ij=0 (null truth) | 1 | P-EXACT | R-EXACT | 0.0 | 0.0 | 20.0 | 0.02 | 0.1900 |
| G3R2b | S6b | path5 | gamma=HIGH but C_ij=0 (null truth) | 1 | P-EXACT | R-EXACT | 0.0 | 0.0 | 20.0 | 0.02 | 0.1791 |

`C_G0` is the noise-free implementation-sanity cell (SGI_G0) and carries no scientific
claim about attainable data. Only **two** non-G0 regimes out of 128 meet the frozen 0.20
criterion, and in both the truth has **zero cross-node coupling by construction** and the
observation bundle is fully ORACLE_FAVOURABLE. The next best non-G0 regime is `G1R2` at
0.5303 — 2.8x the second-best value — so the boundary is a cliff, not a gradient.

## Full table

See `EMPIRICAL_DECISION_TABLE.csv` (129 rows).

## Factor ranking for local intervention recovery

| factor | frozen levels | best NIRE_L | worst NIRE_L | swing | best level | gap of best to 0.20 |
|---|---|---|---|---|---|---|
| coupling_strength(truth) | NONE -> LOW -> MED -> HIGH | 0.580 | 0.914 | 0.334 | NONE | +0.380 |
| pumping_quality | P-EXACT -> P-MULTNOISE -> P-SCALEBIAS -> P-TEMPAGG -> P-SPATIALAGG | 0.706 | 0.850 | 0.143 | P-EXACT | +0.506 |
| head_snr | 2.0 -> 5.0 -> 10.0 -> 20.0 | 0.831 | 0.936 | 0.105 | 20.0 | +0.631 |
| cadence | 1 -> 2 -> 4 -> 13 | 0.824 | 0.914 | 0.091 | 2 | +0.624 |
| hydraulic_memory | LOW -> MED -> HIGH | 0.770 | 0.850 | 0.080 | HIGH | +0.570 |
| observed_node_fraction | 0.4 -> 0.6 -> 0.8 -> 1.0 | 0.831 | 0.894 | 0.064 | 0.8 | +0.631 |
| confounding_rho | 0.0 -> 0.3 -> 0.6 -> 0.9 | 0.828 | 0.858 | 0.030 | 0.9 | +0.628 |
| block_outage | 0 -> 1 -> 2 | 0.836 | 0.859 | 0.022 | 2 | +0.636 |
| recharge_quality | R-EXACT -> R-NOISE -> R-LAG -> R-NOISELAG -> R-SCALE | 0.845 | 0.860 | 0.015 | R-NOISELAG | +0.645 |
| process_noise | 0.05 -> 0.25 -> 1.0 | 0.842 | 0.850 | 0.008 | 1.0 | +0.642 |
| mcar_missingness | 0.0 -> 0.1 -> 0.3 -> 0.5 | 0.842 | 0.850 | 0.008 | 0.0 | +0.642 |
