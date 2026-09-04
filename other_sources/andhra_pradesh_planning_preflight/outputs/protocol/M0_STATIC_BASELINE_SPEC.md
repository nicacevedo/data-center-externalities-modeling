# M0 static baseline specification audit

`M0_REPRODUCTION_STATUS = PARTIAL`

The repository-wide scientific narrative and the Prineville glossary mapping
describe a PSCC-style static planning backbone, but the repository contains no
canonical PSCC implementation, input bundle, manuscript artifact, or frozen
numerical result that can be replayed in this task. No numerical reproduction
was fabricated.

| Item | Repository-supported semantics | Reproduction boundary |
|---|---|---|
| Decision variables | Capacity/siting by location and technology, plus operational assignment/served demand and power-source quantities | Exact indices and bounds unavailable |
| Objective | Weighted planning tradeoff involving cost, carbon, water-scarcity/WSF, renewable energy, and equity | Exact terms, normalization, and weights unavailable |
| Constraints | Demand satisfaction, siting/capacity, power/renewable feasibility, and resource constraints | Canonical algebra and data unavailable |
| Demand | Data-center demand/served workload is part of the model semantics | Series, units, and horizon unavailable |
| Cost inputs | Capital/operating and resource costs are referenced | Canonical files and vintage unavailable |
| Water input | Static WSF/scarcity representation | Exact metric and spatial crosswalk unavailable |
| Power input | Grid and renewable options | Canonical MITEI/PSCC bundle not located |
| Equity | Minimax/MAD-style equity concepts are described | Exact implementation unavailable |
| Spatial unit | Candidate locations/regions | Canonical set unavailable |
| Time horizon | Planning plus operations | Exact horizon unavailable |

Read-only evidence:

- `main_documents/master.tex`, SHA-256
  `83231ddc5cbf3b2682eab972da1254490b3e3178f588da027f92c89c4f830a06`
- `Meta_Prineville_Oregon_v3/modeling/glossary_mapping.tex`, SHA-256
  `8179ae861810fbee853c4da1c5da29e14f896a93d6068d4bcfec8e0da515ca43`

M0 freezes the semantic comparator only. India-specific candidates, demand,
costs, power, WSF, equity choices, spatial units, and horizon still require a
canonical versioned input bundle before any optimization or ablation.
