"""Read-only imports of the frozen Forest City v1 and Prineville modules.

v1 files are never written. Controllers are not copied or retuned.
"""
from __future__ import annotations

import sys

from paths import PRINEVILLE_SRC, V1_SRC

for p in (str(V1_SRC), str(PRINEVILLE_SRC)):
    if p not in sys.path:
        sys.path.insert(0, p)

from forest_city_controller import (  # noqa: E402,F401
    RH_MAX as FC_RH_MAX,
    T_INLET_MAX_C,
    T_INLET_MAX_F,
    forest_city_control_request,
)
from forest_city_structural_reference_v1 import (  # noqa: E402,F401
    EVAP_THERMAL_EFFECTIVENESS_GENERIC_PRIOR,
    FACILITY_EFFECTIVE_DELTA_T_STATUS,
    IT_DELTA_T_STATUS,
    IT_EQUIPMENT_DELTA_T_DESIGN_F,
    IT_EQUIPMENT_DELTA_T_DESIGN_K,
    adiabatic_direct_evaporation,
    iterate_return_air,
    simulate_frame,
    simulate_hour,
)
from prineville_structural_v1 import (  # noqa: E402,F401
    ReturnAirSpec,
    StructuralV1Params,
    simulate_structural_reference_v1,
)
from psychrometrics_adapter import (  # noqa: E402,F401
    MoistAirState,
    c_to_f,
    f_to_c,
    moist_air_state,
    state_from_t_rh,
)
