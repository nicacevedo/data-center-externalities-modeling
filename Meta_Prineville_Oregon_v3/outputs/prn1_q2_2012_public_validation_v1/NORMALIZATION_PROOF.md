# Normalization proof

Frozen v1 airflow: \(m_\mathrm{da} = P_\mathrm{IT}/(c_p\Delta T)\).

Air-stream evaporated water: \(W = m_\mathrm{da}\,\Delta w/\rho_w\).

Conditional on the outdoor state, return-air scenario, and controller (hence on \(\Delta w\)):

\[
\frac{W}{P_\mathrm{IT}} = \frac{\Delta w}{\rho_w\,c_p\,\Delta T}
\]

independent of absolute IT MW. Quarterly WUE is the **IT-energy-weighted** mean of hourly intensity, so scale still cancels, but an unknown hourly load shape that correlates with weather can change the quarter mean. Primary convention: `CONSTANT_NORMALIZED_IT_LOAD`.
