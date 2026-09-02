# Weather × controller 2×2 (MODEL_REPLAY)

Not causal identification. Not gallons. Common UTC window 2012-06-21 through 2012-08-31.

| combination | valid_hours | P(HUMIDIFICATION) | P(OA_FREE) | P(HIGH_RH_MIXING) | P(EVAP_COOLING) | P(MECHANICAL_COOLING) | P(UNRESOLVED) | matches_committed_v2 |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| PRN_weather+PRN_controller | 1251 | 0.43005595523581136 | 0.1374900079936051 | 0.20623501199040767 | 0.22621902478017586 | 0.0 | 0.0 | True |
| PRN_weather+FC_controller | 1251 | 0.0 | 0.8361310951239008 | 0.03117505995203837 | 0.13269384492406075 | 0.0 | 0.0 | True |
| FC_weather+PRN_controller | 1251 | 0.0 | 0.019984012789768184 | 0.7450039968025579 | 0.23501199040767387 | 0.0 | 0.0 | True |
| FC_weather+FC_controller | 1251 | 0.0 | 0.539568345323741 | 0.35411670663469225 | 0.10631494804156674 | 0.0 | 0.0 | True |
