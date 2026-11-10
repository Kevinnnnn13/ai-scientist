# AI Scientist

Source code, reproducibility scripts, and rendered materials for the AI
Scientist manuscript. The repository focuses on the scientific planning agent,
programmatic release authorization, robustness experiments, and figure
generation.

## Repository layout

- `src/`: main agent, release-control, and web-service source code
- `tools/`: experiment orchestration and analysis utilities
- `tests/`: test suite
- `robustness/`: robustness experiment configurations
- `deploy/`: deployment configuration
- `web/`: web interface
- `paper_code/`: manuscript figure generation, packaging, and historical
  implementation snapshot
- `figures/`: rendered main and supplementary figures

## Environment

Create a Python environment and install the base dependencies:

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
```

Figure-generation dependencies are listed separately in
`paper_code/requirements_figures.txt`.

## Configuration

Copy `.env.example` to `.env` and provide API credentials locally. Never commit
the resulting `.env` file. Experimental datasets, logs, model outputs, packaged
builds, and user data are intentionally excluded from version control.

## Figure reproduction

See `paper_code/supplement_figures/README.md` for the figure build commands and
input provenance.

## Scope

This repository preserves the inspected implementation and frozen analysis
scripts. It does not claim that every historical supporting file was under
version control when the original experiments were run.
