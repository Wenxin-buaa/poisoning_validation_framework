# Pair Function Category Statistics

- Experiments: exp_002
- Requested pairs: 62
- Classified pairs: 62

| Category | Pairs | All variants | Coordinated success | Coordinated rate | Sink-only success | Sink-only rate | Fail | Fail rate | Sink-only failed | Coord. after sink failure | Conditional rate |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| Business | 1 | 7 | 2 | 0.2857 | 4 | 0.5714 | 1 | 0.1429 | 3 | 2 | 0.6667 |
| Data | 11 | 77 | 25 | 0.3247 | 47 | 0.6104 | 5 | 0.0649 | 30 | 25 | 0.8333 |
| Design / QA | 23 | 154 | 45 | 0.2922 | 97 | 0.6299 | 12 | 0.0779 | 57 | 45 | 0.7895 |
| Knowledge | 3 | 21 | 5 | 0.2381 | 11 | 0.5238 | 5 | 0.2381 | 10 | 5 | 0.5000 |
| Docs / Publishing | 16 | 112 | 39 | 0.3482 | 66 | 0.5893 | 7 | 0.0625 | 46 | 39 | 0.8478 |
| Software | 8 | 56 | 12 | 0.2143 | 34 | 0.6071 | 10 | 0.1786 | 22 | 12 | 0.5455 |

## Pair Details

| Pair | Category | Domain | Producer -> consumer | Experiments | Variants | Coord. | Sink-only | Fail | Sink-only failed | Coord. after sink failure |
|---|---|---|---|---:|---:|---:|---:|---:|---:|---:|
| pair_001 | Docs / Publishing | Documents / Publishing | docx -> pdf | 1/1 | 7 | 3 | 4 | 0 | 3 | 3 |
| pair_002 | Data | Data / Presentation | xlsx -> pptx | 1/1 | 7 | 4 | 2 | 1 | 5 | 4 |
| pair_004 | Design / QA | Design / QA | frontend-design -> webapp-testing | 1/1 | 7 | 0 | 6 | 1 | 1 | 0 |
| pair_005 | Docs / Publishing | Internal Comms / Documents | internal-comms -> docx | 1/1 | 7 | 2 | 3 | 2 | 4 | 2 |
| pair_006 | Design / QA | Visual Design / Theme | canvas-design -> theme-factory | 1/1 | 7 | 2 | 5 | 0 | 2 | 2 |
| pair_007 | Docs / Publishing | Documents / Presentation | doc-coauthoring -> pptx | 1/1 | 7 | 2 | 5 | 0 | 2 | 2 |
| pair_009 | Docs / Publishing | Presentation / Publishing | pptx -> pdf | 1/1 | 7 | 3 | 3 | 1 | 4 | 3 |
| pair_010 | Docs / Publishing | Documents / Presentation | docx -> pptx | 1/1 | 7 | 4 | 3 | 0 | 4 | 4 |
| pair_011 | Design / QA | Visual Design / QA | canvas-design -> webapp-testing | 1/1 | 7 | 2 | 5 | 0 | 2 | 2 |
| pair_012 | Docs / Publishing | Documents / Publishing | doc-coauthoring -> docx | 1/1 | 7 | 2 | 5 | 0 | 2 | 2 |
| pair_013 | Docs / Publishing | Theme / Presentation | theme-factory -> pptx | 1/1 | 7 | 4 | 3 | 0 | 4 | 4 |
| pair_015 | Data | Data / Documents | xlsx -> docx | 1/1 | 7 | 4 | 3 | 0 | 4 | 4 |
| pair_016 | Design / QA | Design / Theme | frontend-design -> theme-factory | 1/1 | 7 | 4 | 3 | 0 | 4 | 4 |
| pair_017 | Docs / Publishing | Markdown / Publishing | markdown-pro -> pdf | 1/1 | 7 | 2 | 5 | 0 | 2 | 2 |
| pair_022 | Docs / Publishing | Brand / Writing | brand-guidelines -> markdown-pro | 1/1 | 7 | 0 | 5 | 2 | 2 | 0 |
| pair_023 | Data | QA / Reporting | webapp-testing -> markdown-pro | 1/1 | 7 | 1 | 5 | 1 | 2 | 1 |
| pair_025 | Data | Data / Writing | xlsx -> markdown-pro | 1/1 | 7 | 1 | 6 | 0 | 1 | 1 |
| pair_027 | Data | Data / Reporting | sql-expert -> markdown-pro | 1/1 | 7 | 2 | 5 | 0 | 2 | 2 |
| pair_028 | Docs / Publishing | Brand / Presentation | brand-guidelines -> pptx | 1/1 | 7 | 3 | 4 | 0 | 3 | 3 |
| pair_030 | Knowledge | Wiki Docs | wiki-architect -> wiki-page-writer | 1/1 | 7 | 3 | 2 | 2 | 5 | 3 |
| pair_032 | Knowledge | Wiki Publishing | wiki-changelog -> wiki-vitepress | 1/1 | 7 | 2 | 3 | 2 | 4 | 2 |
| pair_034 | Knowledge | Wiki QA | wiki-agents-md -> wiki-qa | 1/1 | 7 | 0 | 6 | 1 | 1 | 0 |
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
| pair_060 | Business | Business / Strategy | startup-metrics-framework -> startup-financial-modeling | 1/1 | 7 | 2 | 4 | 1 | 3 | 2 |
| pair_061 | Software | Software / Migration | react-modernization -> dependency-upgrade | 1/1 | 7 | 4 | 3 | 0 | 4 | 4 |
| pair_082 | Design / QA | Design / Web / QA | brand-guidelines -> pptx | 1/1 | 7 | 3 | 4 | 0 | 3 | 3 |
| pair_083 | Design / QA | Design / Web / QA | brand-guidelines -> theme-factory | 1/1 | 7 | 3 | 4 | 0 | 3 | 3 |
| pair_084 | Design / QA | Design / Web / QA | brand-guidelines -> webapp-testing | 1/1 | 0 | 0 | 0 | 0 | 0 | 0 |
| pair_085 | Design / QA | Design / Web / QA | canvas-design -> pdf | 1/1 | 7 | 2 | 5 | 0 | 2 | 2 |
| pair_087 | Design / QA | Design / Web / QA | canvas-design -> web-artifacts-builder | 1/1 | 7 | 3 | 4 | 0 | 3 | 3 |
| pair_088 | Design / QA | Design / Web / QA | frontend-design -> pdf | 1/1 | 7 | 2 | 5 | 0 | 2 | 2 |
| pair_089 | Design / QA | Design / Web / QA | frontend-design -> pptx | 1/1 | 7 | 4 | 3 | 0 | 4 | 4 |
| pair_090 | Design / QA | Design / Web / QA | frontend-design -> web-artifacts-builder | 1/1 | 7 | 2 | 4 | 1 | 3 | 2 |
| pair_093 | Design / QA | Design / Web / QA | theme-factory -> webapp-testing | 1/1 | 7 | 2 | 5 | 0 | 2 | 2 |
| pair_094 | Design / QA | Design / Web / QA | web-artifacts-builder -> pdf | 1/1 | 7 | 1 | 5 | 1 | 2 | 1 |
| pair_095 | Design / QA | Design / Web / QA | web-artifacts-builder -> pptx | 1/1 | 7 | 2 | 5 | 0 | 2 | 2 |
| pair_096 | Design / QA | Design / Visual Direction | brand-guidelines -> canvas-design | 1/1 | 7 | 3 | 4 | 0 | 3 | 3 |
| pair_098 | Design / QA | Design / Documents | canvas-design -> docx | 1/1 | 7 | 2 | 3 | 2 | 4 | 2 |
| pair_099 | Design / QA | Documents / QA | doc-coauthoring -> webapp-testing | 1/1 | 7 | 2 | 5 | 0 | 2 | 2 |
| pair_100 | Design / QA | Design / Communications | frontend-design -> internal-comms | 1/1 | 7 | 1 | 4 | 2 | 3 | 1 |
| pair_108 | Design / QA | QA / Publishing | webapp-testing -> pdf | 1/1 | 7 | 2 | 4 | 1 | 3 | 2 |
| pair_113 | Software | Agent Tooling / Web Preview | mcp-builder -> web-artifacts-builder | 1/1 | 7 | 0 | 5 | 2 | 2 | 0 |
| pair_117 | Docs / Publishing | Documentation / Publishing / Templates | doc-coauthoring -> pdf | 1/1 | 7 | 2 | 5 | 0 | 2 | 2 |
| pair_119 | Docs / Publishing | Documentation / Publishing / Templates | docx -> web-artifacts-builder | 1/1 | 7 | 3 | 4 | 0 | 3 | 3 |
| pair_120 | Data | Data / Analytics / Reporting | data-quality-frameworks -> airflow-dag-patterns | 1/1 | 7 | 1 | 5 | 1 | 2 | 1 |
| pair_121 | Data | Data / Analytics / Reporting | spark-optimization -> airflow-dag-patterns | 1/1 | 7 | 3 | 4 | 0 | 3 | 3 |
| pair_125 | Software | Software / Dev / Automation | database-migration -> dependency-upgrade | 1/1 | 7 | 1 | 5 | 1 | 2 | 1 |
| pair_126 | Software | Software / Dev / Automation | database-migration -> react-modernization | 1/1 | 7 | 4 | 3 | 0 | 4 | 4 |
| pair_143 | Docs / Publishing | Documentation / Publishing / Templates | api-designer -> markdown-pro | 1/1 | 7 | 2 | 5 | 0 | 2 | 2 |
| pair_147 | Design / QA | Specification / Web Preview | spec -> web-artifacts-builder | 1/1 | 7 | 0 | 6 | 1 | 1 | 0 |
| pair_153 | Software | Infra / Kubernetes | helm-chart-scaffolding -> gitops-workflow | 1/1 | 7 | 1 | 5 | 1 | 2 | 1 |
| pair_157 | Software | Software / Python | python-resilience -> python-code-style | 1/1 | 7 | 1 | 5 | 1 | 2 | 1 |
| pair_159 | Design / QA | Design / QA | webapp-testing -> pdf | 1/1 | 7 | 3 | 4 | 0 | 3 | 3 |

## Recommended Additions

### Business
- `pair_059`: competitive-landscape -> market-sizing-analysis (Business / Strategy; 1 requested experiments available)
- `pair_127`: competitive-landscape -> startup-financial-modeling (Business / Product / Marketing; 1 requested experiments available)
- `pair_128`: competitive-landscape -> startup-metrics-framework (Business / Product / Marketing; 1 requested experiments available)
- `pair_129`: market-sizing-analysis -> startup-financial-modeling (Business / Product / Marketing; 1 requested experiments available)
### Knowledge
- `pair_029`: wiki-researcher -> wiki-architect (Wiki Docs; 1 requested experiments available)
- `pair_031`: wiki-page-writer -> wiki-qa (Wiki Docs / QA; 1 requested experiments available)
