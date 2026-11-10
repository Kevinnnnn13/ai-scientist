# Reproducing the five figures

The `data` directory is unchanged from the frozen plotting inputs. The current
revision corrects text labels to match the inspected implementation:

- Figure 1 exports a hypothesis report, and its search number is a counter.
- Figure 2 labels four as a routing threshold, not a hard global search cap.
- Figure 3 labels the observed additional-search counter.
- Figure 4 describes the observed score-plot write failure without asserting
  an independently reproduced operating-system root cause.
- Figure 5 retains every original response, estimate and test result.

Run from an environment with the packages in `requirements.txt` and Poppler:

```powershell
python -m pip install -r requirements.txt
python -B build.py --pdftoppm "C:\path\to\pdftoppm.exe"
python -B make_composite.py
```

`reproduce.ps1` accepts `-Python` and `-Pdftoppm` paths. No model API or experiment
is invoked. PDF and SVG outputs are editable vector graphics; PNGs are rendered
from the PDFs. The default figure width is 180 mm with embedded Arial fonts
on Windows, or DejaVu Sans if Arial is unavailable. A different font, operating
system or package version can change rendered bytes without changing the data.

`draw_figure1.py` produces Figure 1, `draw_mechanisms.py` produces Figure 2,
and `draw_results.py` produces Figures 3-5. `plot_style.py` defines dimensions,
fonts, colors and drawing primitives. `make_composite.py` produces the separate
five-figure overview in the parent directory without cropping any figure.

The data inputs are checked against `input_provenance.json`; the build writes
`verification_report.json` and `layout_checks.json`. Visual inspection is
recorded separately after the final renders. The historical
`--require-accepted-bytes` option compares against the previous Figure 1 and
should not be used for this intentionally relabelled revision.

`captions.md` contains the current complete manuscript legends. Figure 2 is
an implementation schematic, not an experimental observation. Scientific
proposals in Figures 1 and 3 are untested; their curves are recorded review
scores, not measurements from a completed scientific experiment.
