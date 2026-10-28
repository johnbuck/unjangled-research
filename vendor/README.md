# Vendored dependencies

These libraries are bundled so the readability gate runs with no `pip install`
and reproduces the same numbers on every machine. `scripts/readability_check.py`
puts this directory on `sys.path`.

| Package | Version | Upstream | License | Changes |
|---|---|---|---|---|
| `textstat/` | 0.7.13 | https://github.com/textstat/textstat | MIT, see `textstat/LICENSE` | `backend/utils/_get_cmudict.py`: added `_load_vendored_cmudict()`, which reads `corpora/cmudict/cmudict` directly so nltk is not required. No other changes. |
| `pyphen/` | 0.18.1 | https://github.com/Kozea/Pyphen | GPL-2.0+ / LGPL-2.1+ / MPL-1.1 tri-license, see `pyphen/LICENSE` and `pyphen/COPYING.*` | Unmodified code. Hyphenation dictionaries trimmed to `en_US` and `en_GB`; each keeps its upstream `README_hyph_*.txt` license notice. |
| `corpora/cmudict/` | CMU Pronouncing Dictionary 0.7a, as packaged in `nltk_data` | https://github.com/nltk/nltk_data (`corpora/cmudict`) | BSD-style, terms in `corpora/cmudict/README` | Unmodified. |
