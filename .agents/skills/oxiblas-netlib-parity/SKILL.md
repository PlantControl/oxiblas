---
name: oxiblas-netlib-parity
description: Audit or repair OxiBLAS Rust LAPACK routines for semantic parity with Netlib, using source comparison where code is translated and independent numerical oracles everywhere. Use for correctness reviews of oxiblas-lapack, oxiblas-ndarray LAPACK wrappers, or sparse direct solvers; not for performance work.
---

# OxiBLAS Netlib Parity

Treat parity as an independent-reference claim. Reconstruction, orthogonality,
and passing local tests alone do not prove it; this codebase has shipped routines
whose tests dodged known-wrong paths (see `TODO.md` P0 "fabrication" entries).
Keep a review-only request read-only; implement fixes when they are in scope.

## Classify first

Each routine is one of:

- **Translation**: follows a Netlib routine's structure (names such as `dstemr`,
  `dlarrv`, `dlaed2`, `zgehrd` in comments or helpers). Apply full source-parity
  gates: map labels, loops, branches, and thresholds to the pinned Fortran, and
  preserve any Netlib notice.
- **Reimplementation**: same contract, independent algorithm (e.g. `evd/qz.rs`
  `qz_step`/`givens`). Do not invent a Fortran line mapping. Apply contract and
  differential gates only: status, canonical form, residuals, failure outputs,
  and the reference's numerical guarantees (backward stability, scaling, exact zeros).

Record the classification and the Netlib routine(s) each public entry point
claims to cover (e.g. `Lu::compute` ↔ `dgetrf`, `Qz::compute` ↔ `dgghrd`+`dhgeqz`).
A docstring naming an algorithm is a claim to verify, not evidence.

## Scope and source evidence

Trace reachable helpers with
[trace_rust_lapack_stack.py](scripts/trace_rust_lapack_stack.py) from the repo root:

```bash
python3 <skill-dir>/scripts/trace_rust_lapack_stack.py . Qz::compute
python3 <skill-dir>/scripts/trace_rust_lapack_stack.py . Lu::solve \
  --source-dir crates/oxiblas-lapack/src --source-dir crates/oxiblas-blas/src
```

The tracer is lexical and cannot prove completeness. It misses trait dispatch,
generic `T::method` calls, closures, function values, and macro-generated code;
edges marked `[receiver unresolved; matched by name]` are guesses, and
`--show-ambiguous` lists calls it could not resolve. Default scope is
`crates/oxiblas-lapack/src`; add `oxiblas-blas`, `oxiblas-ndarray`, or
`oxiblas-sparse` when the entry point crosses them. For a full audit, cover all
reachable helpers. For a focused defect, trace affected paths and label the rest
unaudited.

Pin the exact Netlib source (release or commit) and runtime oracle version.
Maintain a branch ledger for a full audit of a translation, distinguishing source
review, dynamic oracle coverage, regression coverage, and unproven paths.

## Numerical evidence

- [Review gates](references/review-gates.md): source, numerical, API, Rust, and
  test gates. Apply the relevant subset to a focused repair.
- [Oracle setup and test matrix](references/oracle-test-matrix.md): wiring a
  Netlib oracle into Cargo, comparators, and structured adversarial cases.

Compare Netlib/LAPACKE semantics: `INFO` versus the `Result`/error variant,
pivots, selected dimension, homogeneous eigenvalues, canonical form, residuals,
and failure outputs. Do not demand identical Schur vectors, singular vectors, or
ordering when the reference leaves them unspecified. Implementation-versus-itself
checks (including `verify()` helpers) establish internal consistency only.

Keep counterexamples and differential checks as persistent tests: exact
regressions in normal `cargo test`, oracle comparisons behind a Cargo feature.
Correctness failures must fail tests, not print. Run affected regressions,
`cargo nextest run -p <crate>` (or `cargo test`), clippy, and relevant feature
variants (`force-scalar`, `parallel`, `max-simd-*`) when SIMD or threading paths
are reachable.

Report the classification, audited stack, mismatches/fixes, commands and
outcomes, baseline failures, and gaps. Claim full parity only with a complete
branch ledger (translations) or complete contract coverage (reimplementations)
plus passing persistent oracle tests. If the oracle cannot run, state that
parity remains unproven.
