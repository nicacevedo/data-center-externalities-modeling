City/Meta/OWRD water-boundary map. No row may be automatically summed with another without an identified accounting relationship.

| boundary_source | canonical_quantity | status | temporal_coverage | automatically_sum | model_role_key_caveat |
|---|---|---|---|---|---|
| Meta annual withdrawal | Q_W_WITH / W_Meta,y | REPORTED | 2014--2024 (11 annual values) | No | Annual campus disclosure; withdrawal, not consumption; no monthly allocation implied. |
| City WATER-COMM + ADD'L WATER service | Q_CITY_METER_SERVICE / W_City,service,m | OBSERVED/REPORTED | 2012-12 to 2026-07 (163 observed months; 2012, 2015, and 2026 partial) | No | Customer municipal-service component; model response; not all-source campus withdrawal. |
| City bulk/hydrant | Q_CITY_BULK_WATER | OBSERVED/REPORTED | 2018-02 to 2026-08 (103 billing months) | No | Billing-month component with unresolved campus/use boundary; service+bulk is diagnostic only. |
| City SWR METER | Q_CITY_SWR_METER | OBSERVED/REPORTED; identity unresolved | 2012-12 to 2026-07 (163 months) | No | Keep separate; naming/numerical proximity does not establish master/submeter or return semantics. |
| City WELL METER FOR SEW | Q_CITY_WELL_METER_SEW | OBSERVED/REPORTED; identity unresolved | 2012-12 to 2026-07 (163 months) | No | Weak OWRD-POD correspondence; do not infer source, sewer, or master/submeter identity. |
| OWRD direct Vitesse/Facebook POD | Q_DIRECT_POD | REPORTED | 2010-10 to 2024-09 (450 reported POD-month rows) | No | Direct-POD reporting boundary; not total Meta withdrawal and not automatically additive to City service. |
| All-source monthly Meta/campus withdrawal | W_Meta,total,m (coverage/report concept; no distinct registry row) | NOT IDENTIFIED | None | No | Service, bulk, SWR/WELL, direct POD, reuse/return/storage, lifecycle, and campus-scope relations do not close a mass balance. |
