# Netlib parity review gates

Use this checklist for every routine in the traced stack. Record evidence, not
just a checked box. Gates marked *(translation)* apply only to routines classified
as translations; all others apply to both.

## Source and structure

- Pin the Netlib release, source URL, or commit, and the runtime oracle library
  version. If they come from different releases, say so.
- *(translation)* Compare the whole routine. Map Fortran labels, loops,
  fallthrough, early exits, and alternate branches to Rust.
- *(translation)* Map transient and sentinel state values, including states that
  arise only after splitting, rejection, or partial convergence.
- *(translation)* Explain every omitted reference branch and algorithmic substitution.
- *(reimplementation)* Name the reference contract being matched and every
  guarantee it gives (stability, exact zeros, sign conventions, failure outputs).
  A comment claiming an algorithm (e.g. "Gu-Eisenstat", "Aasen") is unverified
  until the code matches the published recurrence.
- Check 1-based to 0-based ranges and inclusive endpoints. `Mat<T>` is
  column-major like Fortran, but check `row_stride`/padding assumptions and any
  transpose in `oxiblas-ndarray` or other bridges.
- Verify every helper's dimensional preconditions at each call site, especially
  minimum active-block sizes for shift and sweep kernels.
- Check every reachable helper recursively, including generic SIMD/BLAS kernels
  selected per type or target.

## Numerical semantics

- Machine constants: epsilon versus precision (`dlamch('E')` vs `('P')`), safe
  minimum, overflow limits; per type (`f32`, `f64`, `f16`, `QuadFloat`, complex).
- Norm scope: full matrix versus active submatrix.
- Tolerances and threshold formulas, including scaling before comparison.
- For multi-matrix routines, derive thresholds and residual tests independently
  per operand unless the reference combines them.
- Exceptional shifts, iteration counters, counter resets, and convergence limits.
- Rotation orientation and left/right application.
- Update ranges for the active block, surrounding matrix, and vectors.
- Scaling propagation across every affected block and all return paths.
- Required exact zeros, signs, conjugate ordering, homogeneous eigenvalues.
- Canonicalization after transformations (e.g. `dlagv2` after block swaps).
- Complex routines: conjugation (`dotc` vs `dotu`, `^H` vs `^T`) and SIMD sign
  masks per lane order.

## Pivot and permutation representation

- LAPACK `ipiv` is a sequential swap list; a permutation vector is not. Check
  every producer and consumer of `pivot()`, `perm`, or `ipiv`-like slices agrees
  on which representation it holds, including in `oxiblas-ndarray` wrappers.
- Check pivot application order in solves (forward vs reverse, interleaved with
  the L sweep for banded LU as in `dgbtrs`).
- Banded storage: `kl`/`ku`, fill-in rows from pivoting, and that previously
  computed L columns are not swapped when the reference does not swap them.

## API and failure semantics

- Argument validation order; which inputs return `Err` versus panic. A panic on
  input the reference handles (`n=0`, negative increments in CBLAS-style APIs)
  is a mismatch.
- Quick returns and `n=0`/`n=1` behavior.
- Map each reference `INFO` value to the Rust error variant. Distinguish
  singularity (`INFO>0` with partial factor), non-convergence, rejected swaps,
  and invalid input even if the API collapses them.
- On error, snapshot every caller-visible output the reference defines. When the
  Rust API returns `Err` without partial results, record where it drops outputs
  LAPACK provides (e.g. `dgetrf` returns the factor with `INFO>0`).
- All optional-vector and job/sort combinations.
- Workspace/blocking: blocked, recursive, and parallel variants
  (`compute_blocked`, `compute_recursive`, `compute_blocked_par`) must match the
  unblocked result's contract, not just each other.

## Rust-specific gates

- `unsafe` blocks: bounds, aliasing, and alignment preconditions are enforced on
  every path into them, including negative or zero strides. Safe APIs must not
  permit UB.
- `debug_assert!` versus `assert!`: release builds must still reject invalid input
  the reference rejects.
- Integer overflow and `usize` underflow (`n - 1` with `n=0`, `i - k` in loops).
- Generic `T` paths: a routine correct for `f64` may be wrong for `f32` thresholds
  or complex types; test each type the API exposes.
- Feature- and target-dependent code: SIMD dispatch, `force-scalar`,
  `max-simd-*`, `parallel`. A defect may live in one variant only.

## Swap-specific gates

- Exercise all four adjacent block-size combinations.
- Compare weak and strong stability tests with Netlib.
- Test accepted and rejected swaps against the oracle.
- Validate in an embedded matrix, not only an isolated block.
- Re-standardize every resulting 2x2 block; update both Schur vector sets.
- Verify destination indices after partial movement and rejection.
- Exercise block splitting while moving in both directions.

## Test-review gates

- Search correctness paths for `println!`/`eprintln!`/`dbg!` used instead of
  assertions, early `return` from a test on failure, `#[ignore]`, `assert!(true)`,
  commented-out assertions, and "test removed" notes.
- Search for tolerances widened until a wrong result passes, and for tests that
  restrict inputs (e.g. `n <= 2`, diagonal-only, no pivoting) to dodge a branch.
- Require convergence where the reference converges.
- Check more than NaN absence or zeros below a subdiagonal.
- Use nontrivial triangular factors; identity can mask triangularization.
- Ensure pivoting tests actually swap rows (assert a nontrivial pivot occurred).
- Keep reconstruction and orthogonality checks, but never as canonical-form substitutes.
- Add exact regression cases before random cases.
- Seed random tests deterministically (fixed seed in source).
- Test asymmetric operand scales: `(tiny,1)`, `(1,tiny)`, `(huge,1)`, `(1,huge)`.
- After a search exposes a defect, minimize and freeze the input; otherwise record
  generator, seed, and draw position.
- Differentially compare acceptance, semantic outputs, and canonical form.

## Completion gate

Parity is not established until:

- every reachable routine and (for translations) every reference branch has a
  disposition: source-reviewed, dynamically exercised, regression-covered, or unproven;
- every discovered mismatch has a persistent regression test;
- structured adversarial cases pass;
- the feature-gated differential suite passes repeatedly;
- relevant crate and feature-variant tests pass, with unrelated baselines separated.
