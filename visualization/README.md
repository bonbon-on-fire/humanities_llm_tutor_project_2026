# Visualization

Generate score comparison charts for GPT vs Claude transcript grading.

## Inputs

Reads judged transcript JSON files from:

- `transcripts/<persona_type>/<persona_type>_gpt/transcript_*.json`
- `transcripts/<persona_type>/<persona_type>_claude/transcript_*.json`
- `transcripts/bundles/bundles_gpt/bundle_01/bundle_*.json`
- `transcripts/bundles/bundles_claude/bundle_01/bundle_*.json`

Individual transcript charts are generated separately by version only:
`version_01..06` (6 charts total, each combining all personas).
Bundle Type 01 charts are also generated separately for each persona family.

## Run

```powershell
python -m visualization.run_visualization
```

## Outputs

Written to `visualization/outputs/`:

| # | File | Description |
| - | ---- | ----------- |
| 1-2 | `self_consistency_<provider>_run_correlation.png` | Provider self-consistency heatmaps (GPT vs itself, Claude vs itself) across repeated runs of the same setup, with cell annotations showing correlation and paired count `n`. |
| 3 | `section_discrepancy_by_rubric_section_gpt_vs_claude.png` | Bar chart of per-section grading discrepancies on paired transcripts (mean absolute difference), with `n` and signed mean delta annotations. |
| 4 | `subsection_discrepancy_by_subsection_gpt_vs_claude.png` | Bar chart of per-subsection (criteria-level) grading discrepancies on paired transcripts (mean absolute difference), with `n` and signed mean delta annotations. |
| 5 | `subsection_discrepancy_per_transcript_gpt_vs_claude.png` | Multi-line chart with one colored line per subsection; each point is that subsection's per-transcript absolute GPT-vs-Claude score difference. |
| 6-11 | `individual_grades_version_<NN>_gpt_vs_claude.png` | Line charts of total scores per individual transcript for each version (`01..06`), combining all personas. |
| 12 | `bundle_01_grades_chaotic_gpt_vs_claude.png` | Bundle Type 01 line chart for chaotic bundles only. |
| 13 | `bundle_01_grades_cooperative_gpt_vs_claude.png` | Bundle Type 01 line chart for cooperative bundles only. |
| 14 | `bundle_01_grades_clueless_gpt_vs_claude.png` | Bundle Type 01 line chart for clueless bundles only. |
| 15-16 | `subsection_correlation_heatmap_<provider>_all_personas_normalized.png` | Joined subsection-pair Pearson correlation heatmaps on normalized subsection scores (`score / max`) for each provider (`gpt`, `claude`) across all personas combined. |
| 17-22 | `subsection_correlation_heatmap_<provider>_<persona>_normalized.png` | Subsection-pair Pearson correlation heatmaps on normalized subsection scores (`score / max`), generated separately for each provider (`gpt`, `claude`) and each persona (`chaotic`, `cooperative`, `clueless`). |
| 23-24 | `subsection_level3_correlation_heatmap_<provider>_all_personas.png` | Level-3 rubric-bucket correlation heatmaps (e.g., `1.3.A`) built from per-transcript deduction-point signals, with axis labels including hit counts `n`, generated separately for GPT and Claude across all personas. |

All charts include Pearson r, Spearman rho, and mean scores.

## Alignment

Individual transcripts are matched across providers by composite key:
`student_persona | course | exercise_number | transcript_name`.

Bundle files are matched by filename (e.g. `bundle_001`).

Missing rows in either provider appear as gaps (NaN) in the line charts.
