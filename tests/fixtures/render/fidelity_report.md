# Fidelity Report: Hostile Content Handling

*A fixture for the render-fidelity tracer bullet: text copied from hostile pages must render escaped and whole.*

## Executive Summary

This report carries text copied straight from hostile web pages, so the renderer must escape it before applying any markdown rule. One bullet holds a script tag and another an image with an onerror handler. The [official protocol page](https://example.com/protocol) is cited as a prose link, and generics such as `List<T>` appear in code spans. Everything an author wrote must survive the render [1].

## Key Points

- The renderer must escape markup before its markdown rules run.
- <script>alert('fidelity')</script>
- <img onerror="alert('fidelity')" src=x>
- Bold **survives**, italic *survives*, and code `List<T>` survives.
- A data row containing dashes stays a table row in entry 2.

## Main Analysis

### Findings

The funding subsection below used to end the body under the old bibliography split, and its text never reached the rendered report.

The [protocol page](https://example.com/protocol) keeps a live anchor, while a [script link](javascript:alert(1)), a [draft note](../drafts/note.md) and an [insecure link](http://example.com/insecure) render as plain text with their targets in brackets.

### Sources of funding

Funding came from three public grants and no industry body. The grants ran from 2024 through 2026. No funder reviewed the text before publication [2].

### Comparison Table

| Case | Marker | Note |
|---|---|---|
| alpha | a | normal row |
| dashes | x | --- |
| omega | z | normal row |

## Limitations

The corpus is small and hostile on purpose.

## Bibliography

[1] Author, A. (2024). "Fidelity of hostile renders". Journal of Rendering. https://example.com/fidelity
[2] Author, B. (2023). "Funding disclosure patterns". Grant Review Quarterly. https://example.com/funding

## Appendix: Reproduction

Run the themed renderer against this file and confirm every section, including this appendix, is present.
