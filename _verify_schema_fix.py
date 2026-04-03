import json, re, sys
sys.path.insert(0, r'D:\humanities_llm_tutor_project_2026')
from visualization.run_visualization import _extract_subsection_scores

root_path = r'D:\humanities_llm_tutor_project_2026\transcripts'
import pathlib
root = pathlib.Path(root_path)

results = {}
for path in sorted(root.glob('*/*_*/transcript_*.json')):
    folder = path.parent.name
    try:
        data = json.loads(path.read_text(encoding='utf-8'))
    except:
        continue

    grade = data.get('grade')
    if not isinstance(grade, dict):
        results.setdefault(folder, {'no_grade': 0, 'has_crit': 0, 'no_crit': 0})['no_grade'] += 1
        continue

    scores, maxes = _extract_subsection_scores(grade)
    bucket = 'has_crit' if scores else 'no_crit'
    results.setdefault(folder, {'no_grade': 0, 'has_crit': 0, 'no_crit': 0})[bucket] += 1

print(f"{'Folder':<35} {'has_crit':>9} {'no_crit':>9} {'no_grade':>9}")
print('-' * 64)
for folder, counts in sorted(results.items()):
    print(f"{folder:<35} {counts['has_crit']:>9} {counts['no_crit']:>9} {counts['no_grade']:>9}")
