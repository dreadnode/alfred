# Template sources

Conference-owned files are vendored so papers keep compiling if upstream URLs
change. The ALFRED `main.tex` files are intentionally smaller shells around
those assets; do not replace the venue files with locally modified copies.

The current template assets were retrieved on 2026-08-17 from:

- **NeurIPS 2026:** [official formatting kit](https://media.neurips.cc/Conferences/NeurIPS2026/Formatting_Instructions_For_NeurIPS_2026.zip)
- **ICLR 2026:** [official master-template repository](https://github.com/ICLR/Master-Template/raw/master/iclr2026.zip)
- **ICML 2026:** [official style archive](https://media.icml.cc/Conferences/ICML2026/Styles/icml2026.zip)
- **CVPR 2026:** [official tagged author kit](https://github.com/cvpr-org/author-kit/archive/refs/tags/CVPR2026-v1%28latex%29.zip)
- **AAAI 2026:** the official author-kit link was access-protected, so the
  style and BibTeX files were accepted only after byte-for-byte comparison of
  independent mirrors in
  [AAAI-2026-Latex-Unified](https://github.com/lizhemin15/AAAI-2026-Latex-Unified)
  and [sPyOpenSource/skills](https://github.com/sPyOpenSource/skills/tree/main/research/research-paper-writing/templates/aaai2026).
  The latter also supplied the unified kit's reproducibility checklist.
- **Springer LNCS:** [official proceedings template](https://cms-resources.apps.public.k8s.springernature.io/springer-cms/rest/v1/content/27851904/data/LaTeX2e%20Proceedings%20Template%20ZIP)
- **NDSS 2026:** [official template page](https://www.ndss-symposium.org/ndss2026/submissions/templates/)
- **ACM:** [canonical `acmart` package on CTAN](https://mirrors.ctan.org/macros/latex/contrib/acmart.zip)
- **IEEEtran bibliography style:** [canonical CTAN copy](https://mirrors.ctan.org/macros/latex/contrib/IEEEtran/bibtex/IEEEtran.bst)

The stable `neurips` template intentionally duplicates the three files in
`neurips2026`. A regression test keeps the alias byte-identical to the pinned
version.
