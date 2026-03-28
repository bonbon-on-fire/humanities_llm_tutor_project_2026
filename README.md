# Humanities LLM Tutor Project 2026

An LLM tutor for MIT OpenCourseWare (OCW) focused on humanities and social sciences that guides students through assignments using Socratic dialogue without giving direct answers.

## Quick Start

### Prerequisites
- Python 3.11+
- OpenAI API key: `export OPENAI_API_KEY="your-key"`
- Anthropic API key (for Claude): `export ANTHROPIC_API_KEY="your-key"`

### Installation
```bash
pip install -r requirements.txt
```

### Run the Web UI
```bash
python -m web_ui
# Open http://localhost:5000
```

### Run Terminal UI
```bash
python -m terminal_ui
# Interactive pipeline: select tutor, student, course, exercise, run conversation
```

### Run Batch Experiments
```bash
# Edit BATCH_TYPE (1, 2, or 3) in the file, then run:
python run_batch_gpt.py     # GPT batch experiments
python run_batch_claude.py  # Claude batch experiments
```

Pre-generated batches for experiments are available in `transcripts/batches/` with 198 batch files across 3 experiment types.

## Project Structure

```
├── curriculum/          # Courses and exercises (philosophy, urban_studies)
├── students/            # Student persona prompts (chaotic, chitchat, clueless)
├── tutor/               # Tutor system prompts and LangGraph engine
├── judge/               # LLM-based grading system
│   ├── run_judge_gpt.py         # Single transcript GPT judge
│   ├── run_judge_claude.py      # Single transcript Claude judge
│   ├── run_judge_batch_gpt.py   # Batch GPT judge for bundles
│   ├── run_judge_batch_claude.py # Batch Claude judge for bundles
│   └── ...
├── run_batch_gpt.py     # GPT batch experiment runner
├── run_batch_claude.py  # Claude batch experiment runner
├── transcripts/         # Generated conversation transcripts
│   └── batches/         # 198 batch files for judging experiments
├── web_ui/              # Flask web interface
├── terminal_ui/         # Command-line interface
├── dashboard_ui/        # Transcript/batch review dashboard
├── visualization/       # Score analysis and plotting
└── ui/                  # Batch generation scripts
```

## Key Features

### 🎓 **Socratic Tutoring**
- Never gives direct answers
- Uses guided discovery and bite-sized responses
- Maintains academic integrity (no submission-ready solutions)
- Provides formative feedback without grades

### 👥 **Student Personas**
- **Chaotic**: Challenges boundaries, tests edge cases
- **Chitchat**: Goes off-topic, needs redirection
- **Clueless**: Genuinely confused, needs scaffolding

### 📊 **LLM-based Grading**
- Rubric-based scoring (current: 46 points max)
- GPT and Claude judge comparison
- Single transcript and batch judging modes
- Robust JSON parsing and validation

### 🔬 **Batch Experiments**
- **Type 01**: Same persona + version + exercise (72 batches)
- **Type 02**: Same persona + version, different exercise (54 batches)
- **Type 03**: Different persona, same version + exercise (72 batches)
- Zero overlap within each batch type

## Usage Examples

### Single Transcript Judging
```python
from judge.run_judge_gpt import judge_transcript

result = judge_transcript("chaotic/chaotic_raw/transcript_01")
print(f"Score: {result.total_score}/{result.max_score}")
```

### Batch Judging
```python
from judge.run_judge_batch_gpt import judge_transcript_batch

results = judge_transcript_batch(
    "unused",
    batch_file_path="transcripts/batches/batch_01/batch_001.txt"
)
```

### Batch Experiments (Recommended)
```python
# Edit BATCH_TYPE in run_batch_gpt.py (1, 2, or 3), then:
# python run_batch_gpt.py

# Type 1: Consistency (72 batches)
# Type 2: Cross-exercise (54 batches) 
# Type 3: Persona differentiation (72 batches)
```

### Generate Conversations
```python
from tutor.run_tutor import get_tutor_reply
from students.run_student import get_next_student_message

# See terminal_ui/ for full conversation pipeline
```

## Documentation

- **[PLANNING.md](PLANNING.md)** — Project vision, goals, and architecture decisions
- **[judge/README.md](judge/README.md)** — Grading system documentation
- **[curriculum/README.md](curriculum/README.md)** — Course and exercise structure
- **[students/README.md](students/README.md)** — Student persona system
- **[tutor/README.md](tutor/README.md)** — Tutor engine documentation

## Environment Variables

| Variable | Required | Description |
|----------|----------|-------------|
| `OPENAI_API_KEY` | Yes | OpenAI API key |
| `ANTHROPIC_API_KEY` | For Claude | Anthropic API key |
| `OPENAI_MODEL` | No | Model name (default: `gpt-5.4`) |
| `ANTHROPIC_MODEL` | No | Claude model (default: `claude-sonnet-4-6`) |
| `JUDGE_OPENAI_REASONING_EFFORT` | No | GPT reasoning: `low/medium/high/off` (default: `medium`) |

## Recent Updates

- **Batch Judging System**: Judge multiple transcripts together for comparative analysis
- **Rubric 05 Migration**: Simplified scoring (46 points, no malus deductions)
- **Enhanced JSON Robustness**: Better handling of LLM output variations
- **Batch Generation**: Automated creation of 198 experimental transcript batches