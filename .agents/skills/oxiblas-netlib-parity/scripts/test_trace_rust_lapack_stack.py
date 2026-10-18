#!/usr/bin/env python3
import contextlib
import io
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import trace_rust_lapack_stack as t

SRC = r'''
/* outer /* nested fn fake_nested() {} */ still comment */
pub struct Lu<'a, T> { x: &'a T }

impl<'a, T: Copy> Lu<'a, T> where T: Default {
    pub fn compute(a: &'a [T]) -> Result<Self, ()> {
        let s = "fn fake_string() { helper() }";
        let r = r#"helper("x") fn fake_raw() {}"#;
        let c = '{';
        let q = '\'';
        let l: &'a str = "";
        Self::factor(a);
        helper::<f64>(1.0);
        println!("{}", s);
        Ok(Lu { x: &a[0] })
    }

    fn factor(a: &'a [T]) {
        trailing(a.len());
    }
}

impl<T> core::fmt::Display for Lu<'_, T> {
    fn fmt(&self, f: &mut core::fmt::Formatter<'_>) -> core::fmt::Result { Ok(()) }
}

fn helper<T>(x: T) {}

fn trailing(n: usize) {}
'''


class TraceTest(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.TemporaryDirectory()
        root = Path(self.dir.name)
        (root / "src").mkdir()
        (root / "src" / "lu.rs").write_text(SRC, encoding="utf-8")
        self.root = root
        self.funcs = t.load_funcs(root / "src")

    def tearDown(self):
        self.dir.cleanup()

    def test_masking_ignores_comments_literals_and_lifetimes(self):
        names = sorted(f"{f.owner}::{f.name}" if f.owner else f.name for f in self.funcs.values())
        self.assertEqual(names, ["Lu::compute", "Lu::factor", "Lu::fmt", "helper", "trailing"])

    def test_tree(self):
        out = io.StringIO()
        sys.argv = ["trace", str(self.root), "Lu::compute", "--source-dir", "src"]
        with contextlib.redirect_stdout(out):
            t.main()
        lines = [line.lstrip("│├└─ ").split("  ")[0] for line in out.getvalue().splitlines()]
        self.assertEqual(lines, ["Lu::compute", "Lu::factor", "trailing", "helper"])


if __name__ == "__main__":
    unittest.main()
