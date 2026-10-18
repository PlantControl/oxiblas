# Oracle setup and adversarial test matrix

## Wiring the oracle

Keep the oracle out of shipped crates. Dev-dependencies cannot be optional, so
put oracle tests in an unpublished workspace crate with an opt-in feature,
mirroring `oxiblas-benchmarks`' `compare-openblas`:

```toml
# crates/oxiblas-oracle/Cargo.toml
[package]
publish = false

[dependencies]
oxiblas-lapack.workspace = true
lapack = { version = "<pin>", optional = true }      # LAPACK bindings
netlib-src = { version = "<pin>", optional = true }  # builds reference Netlib

[features]
netlib-oracle = ["dep:lapack", "dep:netlib-src"]
```

Put oracle tests in `tests/netlib_<routine>.rs` under
`#![cfg(feature = "netlib-oracle")]`, and run:

```bash
cargo test -p <oracle-crate> --features netlib-oracle
```

Notes:

- `netlib-src` builds the actual reference LAPACK; record its bundled version.
  OpenBLAS's LAPACK is Netlib-derived but may lag or patch routines; if used,
  record the OpenBLAS version and say so.
- Fortran is column-major, so `Mat<T>` data can usually be passed directly; pass
  the true leading dimension (`row_stride`, not `nrows`) and copy when strided.
- Convert `ipiv` (1-based swap list) explicitly before comparing to `pivot()`.
- If the oracle cannot build in the environment, keep the tests compiling under
  the feature and report parity as unproven.

## Comparators

Compare:

- `INFO` against the Rust `Result` / error variant;
- pivots after representation conversion;
- factor entries only where the reference makes them unique (e.g. LU with the
  same pivot rule, Cholesky); otherwise compare residuals and structure;
- generalized eigenvalues projectively: with `alpha=alphar+i*alphai`, compare
  `|alpha1*beta2-alpha2*beta1|/(|alpha1||beta2|+|alpha2||beta1|)`, handle a zero
  denominator explicitly, match unordered when allowed;
- singular values and symmetric eigenvalues sorted, with tolerance relative to
  `eps * ||A||`; vectors by subspace angle, not entrywise, when multiplicities or
  signs are unspecified;
- canonical form and residuals for each implementation separately;
- promised outputs after non-convergence or rejection.

Compare eigenvalues/vectors only when the fixture is conditioned for it. Record
every omitted comparison and its numerical reason; never weaken a whole suite
because one fixture is ill-conditioned.

## Minimum structured cases (all routines)

| Area | Cases |
| --- | --- |
| Size | `n=0`; `n=1`; `n=2`; just below/above block size and any SIMD width; rectangular `m<n`, `m>n` |
| Pivoting | no swap needed; swap at first step; swap at last step; every step swaps |
| Rank | full; rank-deficient by 1; zero matrix; exactly singular pivot at `k` |
| Scale | ordinary; subnormal/tiny; near-overflow/huge; mixed row/column scale |
| Types | each exposed `T`: `f32`, `f64`, complex, and `f16`/`QuadFloat` if enabled |
| Variants | unblocked, blocked, recursive, parallel; `force-scalar` vs SIMD |
| Layout | owned `Mat`; strided submatrix view; ndarray C- and F-order inputs |
| Strides | BLAS-style APIs with `inc=1`, `inc>1`, `inc<0`, `inc=0` |

## Routine-specific cases

| Routine family | Cases |
| --- | --- |
| LU / banded LU | pivot swap in band; fill-in rows; `kl=0`/`ku=0`; solve with multiple RHS |
| Cholesky / LDLᵀ / Bunch-Kaufman / Aasen | non-SPD failure index; 1x1 vs 2x2 pivots; `n>=3` with off-diagonal coupling |
| QR / COD / column-pivoted QR | rank-deficient least squares; underdetermined minimum-norm solve vs `dgelsy` |
| SVD (QR, D&C) | sizes above the D&C crossover; repeated and zero singular values; deflation |
| Symmetric/Hermitian EVD (QR, D&C, MRRR) | clustered eigenvalues; glued Wilkinson matrices; tridiagonal with zero off-diagonals |
| Nonsymmetric EVD / Schur | real vs complex pairs; defective matrices; balancing on/off |
| QZ / generalized Schur | see below |
| Sparse direct (supernodal, multifrontal) | compare solve against dense LAPACK on the same matrix; singular and structurally singular inputs |

## Generalized Schur canonical form

For `(S,T)`, require `T` upper triangular. Every nonzero `S[i+1,i]` denotes one
isolated 2x2 complex block:

- no neighbor may extend it into an adjacent subdiagonal block;
- the generalized characteristic discriminant must be negative;
- the matching `T` 2x2 block must be diagonal with positive diagonal when the
  reference requires it;
- a real pair must be split into two 1x1 blocks.

| Area | Cases |
| --- | --- |
| 2x2 classification | real unsplit pair; complex pair; nearly repeated pair |
| Triangular factor | identity `B`; nonzero `B[0,1]`; singular diagonal entries |
| Scale | asymmetric A/B scale |
| Swaps | 1x1-1x1; 1x1-2x2; 2x2-1x1; 2x2-2x2 |
| Swap result | accepted; weak-test rejection; strong-test rejection |
| Placement | isolated block; embedded block with nonzero surroundings |
| Reordering | move up; move down; partial movement then rejection |
| Options | vectors off/on independently; sorting off/on |

Distinguish the documented contract from the pinned oracle's observed behavior.
If they differ, record it and test the invariant supported by the exact source.

## Discovery and regression

Use deterministic extreme-scale searches to discover failures, then minimize and
freeze the counterexample as a normal (non-oracle) `#[test]` with literal data.
If minimization is impractical, retain generator, seed, draw count, and bounds.

## Failure patterns worth seeding

From this repo's audits and prior gonum work:

- SIMD complex dot with reversed sign-mask lanes (negated real part);
- swap list treated as a permutation in a wrapper;
- banded LU swapping previously computed L columns;
- `Z` used where `Zᵀ` is required in a rank-deficient solve;
- a "solve" that returns its input unchanged;
- a recurrence correct only for `n<=2`, with tests limited to `n<=2`;
- D&C merge correct only below the crossover size;
- CBLAS-style negative increments read out of bounds;
- a 2x2 real pair accepted as a quasi-triangular block instead of split;
- a complex block tested only with `B=I`;
- early return after failure skipping unscaling or back-permutation;
- combined A/B thresholds hiding asymmetric scaling;
- tests that print non-convergence and continue.
