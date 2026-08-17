# Missing-data and downscaling protocol

The objective is not to make every cell non-missing. It is to preserve identifiability and uncertainty.

## A. Hard annual targets
Never impute a missing annual Meta site target and then treat it as observed. A blank remains blank. A modeled value may be reported separately with provenance `fitted` or `scenario`.

## B. Hourly weather gaps
1. Keep raw observations and quality flags.
2. For isolated gaps of at most 2 consecutive hours, time interpolation may be used for continuous meteorological variables if the bracketing observations pass QC; flag as `interpolated_short_gap`.
3. For longer gaps, use a secondary nearby station or reanalysis only for the missing interval. Fit bias correction on overlapping observed periods by calendar month (and, if needed, hour-of-day); flag the source.
4. Never fill precipitation by linear interpolation.
5. Recompute RH/wet-bulb after gap filling rather than independently interpolating all psychrometric quantities.

## C. Hourly/submonthly IT power when only annual facility electricity is observed
Treat IT power as latent. Recommended baseline:

`P_IT(t) = K_y * u(t)`

where `K_y` is annual/epoch scale and `u(t)` is a bounded utilization profile with mean one after normalization.

For calibration years, solve `K_y` so modeled **facility** electricity closes to the reported annual Meta MWh. That is calibration closure, not validation.

Start with three nested utilization models and retain the simplest one that external evidence supports:
1. flat `u(t)=1`;
2. low-amplitude diurnal/weekly profile;
3. stochastic autocorrelated profile or public hyperscale workload trace.

Never label the resulting hourly IT series measured/observed.

## D. Monthly/hourly site water when only annual withdrawal is observed
Use cooling physics/weather to determine **shape**, then annual closure determines scale in training years.

Recommended decomposition:

`W_with(t) = W_evap(t) + W_humid(t) + W_other(t) + W_discharge_related(t)`

For direct evaporative water, use psychrometric humidity-ratio change and air mass flow. Add only a small number of uncertain ancillary parameters. Fit common/epoch-level parameters across years, not one parameter per month.

Validation hierarchy:
1. held-out annual Meta water;
2. monthly City/Meta meter data if obtained;
3. municipal well/ASR seasonality as an external consistency constraint.

Bundled OWRD City production and Vitesse/Facebook direct POD series are used in `src/owrd_water_model_validation.py` as that external consistency layer. They are not monthly campus meter data and are not calibration targets.

## E. Water consumption vs withdrawal
Preferred:

`consumption = withdrawal - wastewater discharge`

when both are observed on compatible boundaries.

If discharge is unavailable, estimate consumption from the cooling-system mass balance / cycles-of-concentration range and report an uncertainty interval. Do not simply rename withdrawal as consumption.

## F. Grid emissions
For each hour:

`CO2_location(t) = E_grid(t) * EF_physical(t) + CO2_onsite(t)`

Use the best available regional/consumption-based physical intensity. Aggregate to annual and compare against Meta location-based Scope 2.

Do not tune physical emissions to the market-based value; market-based emissions are a separate accounting output.

## G. Building commissioning dates
Do not statistically impute a calendar date as a fact. If records establish only an interval, represent `commissioning_date_low` and `commissioning_date_high`. In sensitivity runs, sample or enumerate plausible dates inside the interval.

## H. Structural breaks / technology epochs
Use change-point tests only to propose candidate breaks. A break becomes a named physical technology/capacity epoch only when a permit, completion record, engineering document or other independent evidence supports the interpretation.

Current annual screening output is in `outputs/candidate_annual_breaks.csv`.

## I. Uncertainty propagation
At minimum propagate uncertainty in:
- latent utilization shape;
- evaporative effectiveness;
- supply temperature / humidity bounds;
- fan and other facility overhead;
- building commissioning interval;
- water ancillary/loss factor;
- grid emission factor accounting boundary;
- any station/reanalysis weather gap fill.

Report median plus 5/95 or 2.5/97.5 percentiles for inferred hourly/seasonal quantities. Report the actual Meta annual observations without artificial uncertainty unless the source itself provides it.
