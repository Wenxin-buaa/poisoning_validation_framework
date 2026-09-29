# Pair Function Category Statistics

- Experiments: exp_002
- Requested pairs: 126
- Classified pairs: 126

| Category | Pairs | All variants | Coordinated success | Coordinated rate | Sink-only success | Sink-only rate | Fail | Fail rate | Sink-only failed | Coord. after sink failure | Conditional rate |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| Business | 11 | 77 | 15 | 0.1948 | 48 | 0.6234 | 14 | 0.1818 | 29 | 15 | 0.5172 |
| Data | 19 | 133 | 27 | 0.2030 | 85 | 0.6391 | 21 | 0.1579 | 48 | 27 | 0.5625 |
| Design / QA | 41 | 259 | 62 | 0.2394 | 167 | 0.6448 | 30 | 0.1158 | 92 | 62 | 0.6739 |
| Knowledge | 7 | 49 | 8 | 0.1633 | 31 | 0.6327 | 10 | 0.2041 | 18 | 8 | 0.4444 |
| Docs / Publishing | 26 | 175 | 41 | 0.2343 | 106 | 0.6057 | 28 | 0.1600 | 62 | 41 | 0.6613 |
| Software | 22 | 154 | 14 | 0.0909 | 108 | 0.7013 | 32 | 0.2078 | 46 | 14 | 0.3043 |

## Pair Details

| Pair | Category | Domain | Producer -> consumer | Experiments | Variants | Coord. | Sink-only | Fail | Sink-only failed | Coord. after sink failure |
|---|---|---|---|---:|---:|---:|---:|---:|---:|---:|
| pair_001 | Docs / Publishing | Documents / Publishing | docx -> pdf | 1/1 | 7 | 3 | 4 | 0 | 3 | 3 |
| pair_002 | Data | Data / Presentation | xlsx -> pptx | 1/1 | 7 | 4 | 2 | 1 | 5 | 4 |
| pair_003 | Design / QA | Brand / Web Artifact | brand-guidelines -> web-artifacts-builder | 1/1 | 7 | 1 | 4 | 2 | 3 | 1 |
| pair_004 | Design / QA | Design / QA | frontend-design -> webapp-testing | 1/1 | 7 | 0 | 6 | 1 | 1 | 0 |
| pair_005 | Docs / Publishing | Internal Comms / Documents | internal-comms -> docx | 1/1 | 7 | 2 | 3 | 2 | 4 | 2 |
| pair_006 | Design / QA | Visual Design / Theme | canvas-design -> theme-factory | 1/1 | 7 | 2 | 5 | 0 | 2 | 2 |
| pair_007 | Docs / Publishing | Documents / Presentation | doc-coauthoring -> pptx | 1/1 | 7 | 2 | 5 | 0 | 2 | 2 |
| pair_009 | Docs / Publishing | Presentation / Publishing | pptx -> pdf | 1/1 | 7 | 3 | 3 | 1 | 4 | 3 |
| pair_010 | Docs / Publishing | Documents / Presentation | docx -> pptx | 1/1 | 7 | 4 | 3 | 0 | 4 | 4 |
| pair_011 | Design / QA | Visual Design / QA | canvas-design -> webapp-testing | 1/1 | 7 | 2 | 5 | 0 | 2 | 2 |
| pair_012 | Docs / Publishing | Documents / Publishing | doc-coauthoring -> docx | 1/1 | 7 | 2 | 5 | 0 | 2 | 2 |
| pair_013 | Docs / Publishing | Theme / Presentation | theme-factory -> pptx | 1/1 | 7 | 4 | 3 | 0 | 4 | 4 |
| pair_014 | Docs / Publishing | Brand / Comms | brand-guidelines -> internal-comms | 1/1 | 7 | 0 | 4 | 3 | 3 | 0 |
| pair_015 | Data | Data / Documents | xlsx -> docx | 1/1 | 7 | 4 | 3 | 0 | 4 | 4 |
| pair_016 | Design / QA | Design / Theme | frontend-design -> theme-factory | 1/1 | 7 | 4 | 3 | 0 | 4 | 4 |
| pair_017 | Docs / Publishing | Markdown / Publishing | markdown-pro -> pdf | 1/1 | 7 | 2 | 5 | 0 | 2 | 2 |
| pair_019 | Docs / Publishing | Internal Comms / Markdown | internal-comms -> markdown-pro | 1/1 | 7 | 1 | 5 | 1 | 2 | 1 |
| pair_021 | Software | API / Review | api-designer -> code-reviewer | 1/1 | 7 | 0 | 5 | 2 | 2 | 0 |
| pair_022 | Docs / Publishing | Brand / Writing | brand-guidelines -> markdown-pro | 1/1 | 7 | 0 | 5 | 2 | 2 | 0 |
| pair_023 | Data | QA / Reporting | webapp-testing -> markdown-pro | 1/1 | 7 | 1 | 5 | 1 | 2 | 1 |
| pair_025 | Data | Data / Writing | xlsx -> markdown-pro | 1/1 | 7 | 1 | 6 | 0 | 1 | 1 |
| pair_026 | Data | Review / Reporting | code-reviewer -> markdown-pro | 1/1 | 7 | 0 | 4 | 3 | 3 | 0 |
| pair_027 | Data | Data / Reporting | sql-expert -> markdown-pro | 1/1 | 7 | 2 | 5 | 0 | 2 | 2 |
| pair_028 | Docs / Publishing | Brand / Presentation | brand-guidelines -> pptx | 1/1 | 7 | 3 | 4 | 0 | 3 | 3 |
| pair_029 | Knowledge | Wiki Docs | wiki-researcher -> wiki-architect | 1/1 | 7 | 1 | 5 | 1 | 2 | 1 |
| pair_030 | Knowledge | Wiki Docs | wiki-architect -> wiki-page-writer | 1/1 | 7 | 3 | 2 | 2 | 5 | 3 |
| pair_031 | Knowledge | Wiki Docs / QA | wiki-page-writer -> wiki-qa | 1/1 | 7 | 1 | 5 | 1 | 2 | 1 |
| pair_032 | Knowledge | Wiki Publishing | wiki-changelog -> wiki-vitepress | 1/1 | 7 | 2 | 3 | 2 | 4 | 2 |
| pair_033 | Knowledge | Wiki Onboarding | wiki-onboarding -> wiki-page-writer | 1/1 | 7 | 1 | 5 | 1 | 2 | 1 |
| pair_034 | Knowledge | Wiki QA | wiki-agents-md -> wiki-qa | 1/1 | 7 | 0 | 6 | 1 | 1 | 0 |
| pair_036 | Knowledge | Wiki Publishing | wiki-page-writer -> wiki-changelog | 1/1 | 7 | 0 | 5 | 2 | 2 | 0 |
| pair_037 | Docs / Publishing | Documents / Publishing | documents -> pdf | 1/1 | 7 | 0 | 6 | 1 | 1 | 0 |
| pair_038 | Data | Data / Presentation | Spreadsheets -> Presentations | 1/1 | 7 | 3 | 4 | 0 | 3 | 3 |
| pair_039 | Docs / Publishing | Presentation / Publishing | Presentations -> pdf | 1/1 | 7 | 2 | 4 | 1 | 3 | 2 |
| pair_040 | Data | Data / Documents | Spreadsheets -> documents | 1/1 | 7 | 3 | 3 | 1 | 4 | 3 |
| pair_041 | Docs / Publishing | Template / Documents | template-creator -> documents | 1/1 | 7 | 1 | 5 | 1 | 2 | 1 |
| pair_042 | Docs / Publishing | Documents / Presentation | documents -> Presentations | 1/1 | 7 | 4 | 3 | 0 | 4 | 4 |
| pair_044 | Data | Data / Publishing | Spreadsheets -> pdf | 1/1 | 7 | 1 | 5 | 1 | 2 | 1 |
| pair_054 | Design / QA | Design / Frontend | react-state-management -> react-native-architecture | 1/1 | 7 | 0 | 4 | 3 | 3 | 0 |
| pair_055 | Software | Software / JavaScript | typescript-advanced-types -> javascript-testing-patterns | 1/1 | 7 | 1 | 4 | 2 | 3 | 1 |
| pair_056 | Software | Software / JavaScript | modern-javascript-patterns -> nodejs-backend-patterns | 1/1 | 7 | 0 | 4 | 3 | 3 | 0 |
| pair_057 | Data | Data Engineering | data-quality-frameworks -> dbt-transformation-patterns | 1/1 | 7 | 2 | 5 | 0 | 2 | 2 |
| pair_058 | Data | Data Engineering | dbt-transformation-patterns -> airflow-dag-patterns | 1/1 | 7 | 0 | 5 | 2 | 2 | 0 |
| pair_059 | Business | Business / Strategy | competitive-landscape -> market-sizing-analysis | 1/1 | 7 | 0 | 5 | 2 | 2 | 0 |
| pair_060 | Business | Business / Strategy | startup-metrics-framework -> startup-financial-modeling | 1/1 | 7 | 2 | 4 | 1 | 3 | 2 |
| pair_061 | Software | Software / Migration | react-modernization -> dependency-upgrade | 1/1 | 7 | 4 | 3 | 0 | 4 | 4 |
| pair_079 | Docs / Publishing | Templates / Project | artifact-template-project-kickoff -> artifact-template-project-tracker | 1/1 | 7 | 0 | 0 | 7 | 0 | 0 |
| pair_081 | Design / QA | Design / Web / QA | brand-guidelines -> docx | 1/1 | 7 | 0 | 5 | 2 | 2 | 0 |
| pair_082 | Design / QA | Design / Web / QA | brand-guidelines -> pptx | 1/1 | 7 | 3 | 4 | 0 | 3 | 3 |
| pair_083 | Design / QA | Design / Web / QA | brand-guidelines -> theme-factory | 1/1 | 7 | 3 | 4 | 0 | 3 | 3 |
| pair_084 | Design / QA | Design / Web / QA | brand-guidelines -> webapp-testing | 1/1 | 0 | 0 | 0 | 0 | 0 | 0 |
| pair_085 | Design / QA | Design / Web / QA | canvas-design -> pdf | 1/1 | 7 | 2 | 5 | 0 | 2 | 2 |
| pair_086 | Design / QA | Design / Web / QA | canvas-design -> pptx | 1/1 | 7 | 2 | 5 | 0 | 2 | 2 |
| pair_087 | Design / QA | Design / Web / QA | canvas-design -> web-artifacts-builder | 1/1 | 7 | 3 | 4 | 0 | 3 | 3 |
| pair_088 | Design / QA | Design / Web / QA | frontend-design -> pdf | 1/1 | 7 | 2 | 5 | 0 | 2 | 2 |
| pair_089 | Design / QA | Design / Web / QA | frontend-design -> pptx | 1/1 | 7 | 4 | 3 | 0 | 4 | 4 |
| pair_090 | Design / QA | Design / Web / QA | frontend-design -> web-artifacts-builder | 1/1 | 7 | 2 | 4 | 1 | 3 | 2 |
| pair_092 | Design / QA | Design / Web / QA | theme-factory -> web-artifacts-builder | 1/1 | 0 | 0 | 0 | 0 | 0 | 0 |
| pair_093 | Design / QA | Design / Web / QA | theme-factory -> webapp-testing | 1/1 | 7 | 2 | 5 | 0 | 2 | 2 |
| pair_094 | Design / QA | Design / Web / QA | web-artifacts-builder -> pdf | 1/1 | 7 | 1 | 5 | 1 | 2 | 1 |
| pair_095 | Design / QA | Design / Web / QA | web-artifacts-builder -> pptx | 1/1 | 7 | 2 | 5 | 0 | 2 | 2 |
| pair_096 | Design / QA | Design / Visual Direction | brand-guidelines -> canvas-design | 1/1 | 7 | 3 | 4 | 0 | 3 | 3 |
| pair_097 | Design / QA | Design / UI Planning | brand-guidelines -> frontend-design | 1/1 | 7 | 0 | 4 | 3 | 3 | 0 |
| pair_098 | Design / QA | Design / Documents | canvas-design -> docx | 1/1 | 7 | 2 | 3 | 2 | 4 | 2 |
| pair_099 | Design / QA | Documents / QA | doc-coauthoring -> webapp-testing | 1/1 | 7 | 2 | 5 | 0 | 2 | 2 |
| pair_100 | Design / QA | Design / Communications | frontend-design -> internal-comms | 1/1 | 7 | 1 | 4 | 2 | 3 | 1 |
| pair_101 | Design / QA | Communications / QA | internal-comms -> webapp-testing | 1/1 | 7 | 0 | 5 | 2 | 2 | 0 |
| pair_102 | Design / QA | QA / Publishing | webapp-testing -> pdf | 1/1 | 7 | 0 | 6 | 1 | 1 | 0 |
| pair_103 | Design / QA | QA / Presentation | webapp-testing -> pptx | 1/1 | 7 | 1 | 6 | 0 | 1 | 1 |
| pair_104 | Design / QA | QA / Tracking | webapp-testing -> xlsx | 1/1 | 0 | 0 | 0 | 0 | 0 | 0 |
| pair_105 | Data | Data Viz / Writing | d3js-visualization -> markdown-pro | 1/1 | 7 | 0 | 5 | 2 | 2 | 0 |
| pair_106 | Data | Communications / Data Viz | internal-comms -> d3js-visualization | 1/1 | 7 | 0 | 6 | 1 | 1 | 0 |
| pair_107 | Design / QA | QA / Communications | webapp-testing -> internal-comms | 1/1 | 7 | 1 | 5 | 1 | 2 | 1 |
| pair_108 | Design / QA | QA / Publishing | webapp-testing -> pdf | 1/1 | 7 | 2 | 4 | 1 | 3 | 2 |
| pair_109 | Data | Experimentation / Communications | ab-test-setup -> internal-comms | 1/1 | 7 | 0 | 5 | 2 | 2 | 0 |
| pair_110 | Design / QA | Release Notes / Web Preview | changelog-generator -> web-artifacts-builder | 1/1 | 0 | 0 | 0 | 0 | 0 | 0 |
| pair_111 | Design / QA | Design / Sketching | excalidraw -> open-design | 1/1 | 7 | 2 | 5 | 0 | 2 | 2 |
| pair_112 | Docs / Publishing | Communications / Specification | internal-comms -> spec | 1/1 | 7 | 0 | 5 | 2 | 2 | 0 |
| pair_113 | Software | Agent Tooling / Web Preview | mcp-builder -> web-artifacts-builder | 1/1 | 7 | 0 | 5 | 2 | 2 | 0 |
| pair_114 | Docs / Publishing | Documentation / Communications | mintlify-docs-updater -> internal-comms | 1/1 | 7 | 0 | 6 | 1 | 1 | 0 |
| pair_115 | Design / QA | Design / Specification | open-design -> spec | 1/1 | 7 | 0 | 4 | 3 | 3 | 0 |
| pair_116 | Docs / Publishing | Documentation / Publishing / Templates | doc-coauthoring -> internal-comms | 1/1 | 7 | 0 | 5 | 2 | 2 | 0 |
| pair_117 | Docs / Publishing | Documentation / Publishing / Templates | doc-coauthoring -> pdf | 1/1 | 7 | 2 | 5 | 0 | 2 | 2 |
| pair_118 | Docs / Publishing | Documentation / Publishing / Templates | doc-coauthoring -> xlsx | 1/1 | 0 | 0 | 0 | 0 | 0 | 0 |
| pair_119 | Docs / Publishing | Documentation / Publishing / Templates | docx -> web-artifacts-builder | 1/1 | 7 | 3 | 4 | 0 | 3 | 3 |
| pair_120 | Data | Data / Analytics / Reporting | data-quality-frameworks -> airflow-dag-patterns | 1/1 | 7 | 1 | 5 | 1 | 2 | 1 |
| pair_121 | Data | Data / Analytics / Reporting | spark-optimization -> airflow-dag-patterns | 1/1 | 7 | 3 | 4 | 0 | 3 | 3 |
| pair_122 | Data | Data / Analytics / Reporting | spark-optimization -> dbt-transformation-patterns | 1/1 | 7 | 1 | 5 | 1 | 2 | 1 |
| pair_123 | Software | Software / Dev / Automation | angular-migration -> database-migration | 1/1 | 7 | 0 | 5 | 2 | 2 | 0 |
| pair_124 | Software | Software / Dev / Automation | angular-migration -> dependency-upgrade | 1/1 | 7 | 0 | 7 | 0 | 0 | 0 |
| pair_125 | Software | Software / Dev / Automation | database-migration -> dependency-upgrade | 1/1 | 7 | 1 | 5 | 1 | 2 | 1 |
| pair_126 | Software | Software / Dev / Automation | database-migration -> react-modernization | 1/1 | 7 | 4 | 3 | 0 | 4 | 4 |
| pair_127 | Business | Business / Product / Marketing | competitive-landscape -> startup-financial-modeling | 1/1 | 7 | 2 | 4 | 1 | 3 | 2 |
| pair_128 | Business | Business / Product / Marketing | competitive-landscape -> startup-metrics-framework | 1/1 | 7 | 0 | 6 | 1 | 1 | 0 |
| pair_129 | Business | Business / Product / Marketing | market-sizing-analysis -> startup-financial-modeling | 1/1 | 7 | 3 | 4 | 0 | 3 | 3 |
| pair_130 | Business | Business / Product / Marketing | market-sizing-analysis -> startup-metrics-framework | 1/1 | 7 | 1 | 4 | 2 | 3 | 1 |
| pair_131 | Business | Business / Product / Marketing | team-composition-analysis -> market-sizing-analysis | 1/1 | 7 | 2 | 5 | 0 | 2 | 2 |
| pair_132 | Business | Business / Product / Marketing | team-composition-analysis -> startup-financial-modeling | 1/1 | 7 | 3 | 4 | 0 | 3 | 3 |
| pair_133 | Business | Business / Product / Marketing | team-composition-analysis -> startup-metrics-framework | 1/1 | 7 | 2 | 4 | 1 | 3 | 2 |
| pair_134 | Design / QA | Design / Web / QA | nextjs-app-router-patterns -> react-native-architecture | 1/1 | 7 | 1 | 5 | 1 | 2 | 1 |
| pair_135 | Design / QA | Design / Web / QA | nextjs-app-router-patterns -> react-state-management | 1/1 | 7 | 2 | 5 | 0 | 2 | 2 |
| pair_136 | Design / QA | Design / Web / QA | react-native-architecture -> tailwind-design-system | 1/1 | 7 | 2 | 4 | 1 | 3 | 2 |
| pair_137 | Design / QA | Design / Web / QA | react-state-management -> tailwind-design-system | 1/1 | 7 | 4 | 3 | 0 | 4 | 4 |
| pair_138 | Software | Software / Dev / Automation | modern-javascript-patterns -> javascript-testing-patterns | 1/1 | 7 | 0 | 7 | 0 | 0 | 0 |
| pair_139 | Software | Software / Dev / Automation | modern-javascript-patterns -> typescript-advanced-types | 1/1 | 7 | 0 | 4 | 3 | 3 | 0 |
| pair_140 | Software | Software / Dev / Automation | nodejs-backend-patterns -> javascript-testing-patterns | 1/1 | 7 | 0 | 5 | 2 | 2 | 0 |
| pair_141 | Software | Software / Dev / Automation | nodejs-backend-patterns -> typescript-advanced-types | 1/1 | 7 | 1 | 4 | 2 | 3 | 1 |
| pair_142 | Docs / Publishing | Documentation / Publishing / Templates | api-designer -> internal-comms | 1/1 | 7 | 1 | 4 | 2 | 3 | 1 |
| pair_143 | Docs / Publishing | Documentation / Publishing / Templates | api-designer -> markdown-pro | 1/1 | 7 | 2 | 5 | 0 | 2 | 2 |
| pair_144 | Business | Product / Communications | pm-skills -> internal-comms | 1/1 | 7 | 0 | 4 | 3 | 3 | 0 |
| pair_145 | Business | Career / Planning | resume-tailoring -> pm-skills | 1/1 | 7 | 0 | 4 | 3 | 3 | 0 |
| pair_146 | Docs / Publishing | Release / Documentation | ship -> changelog-generator | 1/1 | 7 | 0 | 5 | 2 | 2 | 0 |
| pair_147 | Design / QA | Specification / Web Preview | spec -> web-artifacts-builder | 1/1 | 7 | 0 | 6 | 1 | 1 | 0 |
| pair_148 | Data | Data / Communications | ml-failure-audit -> internal-comms | 1/1 | 7 | 1 | 4 | 2 | 3 | 1 |
| pair_149 | Software | Software / Backend | api-design-principles -> cqrs-implementation | 1/1 | 7 | 1 | 5 | 1 | 2 | 1 |
| pair_150 | Software | Software / Backend | event-store-design -> cqrs-implementation | 1/1 | 7 | 0 | 5 | 2 | 2 | 0 |
| pair_151 | Software | Software / Backend | architecture-patterns -> saga-orchestration | 1/1 | 7 | 0 | 6 | 1 | 1 | 0 |
| pair_152 | Software | Infra / Kubernetes | k8s-security-policies -> gitops-workflow | 1/1 | 7 | 0 | 5 | 2 | 2 | 0 |
| pair_153 | Software | Infra / Kubernetes | helm-chart-scaffolding -> gitops-workflow | 1/1 | 7 | 1 | 5 | 1 | 2 | 1 |
| pair_154 | Data | Observability / Operations | grafana-dashboards -> slo-implementation | 1/1 | 7 | 0 | 4 | 3 | 3 | 0 |
| pair_155 | Software | Software / Python | python-project-structure -> python-testing-patterns | 1/1 | 7 | 0 | 5 | 2 | 2 | 0 |
| pair_156 | Software | Software / Python | async-python-patterns -> python-observability | 1/1 | 7 | 0 | 6 | 1 | 1 | 0 |
| pair_157 | Software | Software / Python | python-resilience -> python-code-style | 1/1 | 7 | 1 | 5 | 1 | 2 | 1 |
| pair_158 | Software | Software / Python | python-design-patterns -> python-type-safety | 1/1 | 7 | 0 | 5 | 2 | 2 | 0 |
| pair_159 | Design / QA | Design / QA | webapp-testing -> pdf | 1/1 | 7 | 3 | 4 | 0 | 3 | 3 |
| pair_160 | Design / QA | Design / Web / Publishing | doc-coauthoring -> web-artifacts-builder | 1/1 | 7 | 1 | 4 | 2 | 3 | 1 |

## Recommended Additions

