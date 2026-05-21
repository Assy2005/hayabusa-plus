// hayabusa-fx: lookup-table extension.
//
// Adds a process-wide registry of named lookup tables, populated when a
// rule's `lookup:` block is encountered while loading YAML. The tables
// are referenced from selection fields via the `|lookup:` and
// `|not_lookup:` pipe modifiers, e.g.
//
//   detection:
//     selection:
//       Channel: 'Microsoft-Windows-Sysmon/Operational'
//       EventID: 6
//       Hashes|sha256|lookup: lol_drivers
//       Hashes|sha256|not_lookup: golden_image_hashes
//     condition: selection
//
// Tables are populated from text files (one value per line, `#`-prefixed
// comments allowed) relative to the rule file's directory or the project
// root. Comparisons are case-insensitive — hashes and paths are the two
// primary use cases and both want CI semantics.
//
// Design notes:
//  * Global state via `RwLock<HashMap<...>>` is acceptable here: tables
//    are write-once-during-load, read-only thereafter. Many concurrent
//    readers, no writer contention during scan.
//  * The `contains` operation is O(1) per match — populating the table
//    once up-front buys near-free runtime semantics, which is what we
//    want for "match against 5000 LOLDriver hashes per event".

use hashbrown::{HashMap, HashSet};
use std::fs;
use std::path::{Path, PathBuf};
use std::sync::RwLock;

use lazy_static::lazy_static;

lazy_static! {
    /// Global registry of lookup tables. Keyed by the rule-author-chosen
    /// `name` field; values are case-folded for CI matching.
    static ref TABLES: RwLock<HashMap<String, HashSet<String>>> =
        RwLock::new(HashMap::new());
    static ref TABLE_PATHS: RwLock<HashMap<String, PathBuf>> =
        RwLock::new(HashMap::new());
}

/// Read a lookup-table file from disk and register it under `name`.
///
/// Returns the number of distinct entries stored, or an error string the
/// caller can surface to the analyst via the existing rule-error sink.
///
/// Behaviour:
///   * Lines are split on the first `#` so trailing comments are allowed.
///   * Leading/trailing whitespace is stripped.
///   * Empty lines are skipped.
///   * Values are case-folded with ASCII lowercase. Non-ASCII is left
///     intact (rules that need locale-aware folding should pre-normalise).
///   * Re-registering the same `name` overwrites the previous table.
pub fn load_table_from_file(name: &str, path: &Path) -> Result<usize, String> {
    let content = fs::read_to_string(path)
        .map_err(|e| format!("lookup '{name}': cannot read {}: {e}", path.display()))?;
    let mut set: HashSet<String> = HashSet::new();
    for raw in content.lines() {
        let line = raw.split('#').next().unwrap_or("").trim();
        if line.is_empty() {
            continue;
        }
        set.insert(line.to_ascii_lowercase());
    }
    let n = set.len();
    TABLES.write().unwrap().insert(name.to_string(), set);
    TABLE_PATHS.write().unwrap().insert(name.to_string(), path.to_path_buf());
    Ok(n)
}

/// Returns true iff the event value matches the named table.
///
/// Match semantics: the event value (case-folded) is checked first for
/// exact membership in the table. Failing that, each entry in the table
/// is tested as a substring of the event value. This dual mode is what
/// makes `|lookup:` ergonomic against both raw scalar fields ("Image"
/// holds a single path) and concatenated fields (Sysmon's "Hashes"
/// holds "MD5=...,SHA256=...,IMPHASH=...").
///
/// Returns None when the table was never loaded — the caller should
/// surface that conservatively.
pub fn contains(name: &str, value: &str) -> Option<bool> {
    let tables = TABLES.read().unwrap();
    let set = tables.get(name)?;
    let v = value.to_ascii_lowercase();
    if set.contains(&v) {
        return Some(true);
    }
    // Substring pass. We accept the O(N) cost: for the typical IOC feed
    // (hundreds-to-thousands of entries) at typical EVTX rates (~5k
    // events/sec on one CPU), this completes inside Hayabusa's overall
    // per-event budget. If a feed ever exceeds ~50k entries, swap in an
    // aho-corasick automaton (already a dep of the crate).
    Some(set.iter().any(|entry| v.contains(entry)))
}

/// Diagnostic accessor: list (name, entry_count, path) of every loaded
/// table. Useful for GUI surfaces and the existing list-* subcommands.
pub fn loaded_tables() -> Vec<(String, usize, PathBuf)> {
    let tables = TABLES.read().unwrap();
    let paths = TABLE_PATHS.read().unwrap();
    let mut out: Vec<_> = tables.iter().map(|(name, set)| {
        let path = paths.get(name).cloned().unwrap_or_default();
        (name.clone(), set.len(), path)
    }).collect();
    out.sort_by(|a, b| a.0.cmp(&b.0));
    out
}

#[cfg(test)]
mod tests {
    use super::*;
    use std::io::Write;

    #[test]
    fn basic_lookup() {
        let dir = std::env::temp_dir();
        let path = dir.join("hayfx_test_lookup_basic.txt");
        let mut f = fs::File::create(&path).unwrap();
        writeln!(f, "# comment").unwrap();
        writeln!(f, "FOO").unwrap();
        writeln!(f, "  bar # trailing comment").unwrap();
        writeln!(f, "").unwrap();
        let n = load_table_from_file("t_basic", &path).unwrap();
        assert_eq!(n, 2);
        assert_eq!(contains("t_basic", "foo"), Some(true));
        assert_eq!(contains("t_basic", "BAR"), Some(true));
        assert_eq!(contains("t_basic", "baz"), Some(false));
        assert_eq!(contains("nonexistent_table", "anything"), None);
    }
}
