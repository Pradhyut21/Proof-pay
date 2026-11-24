use std::fs;

use panelproof_scoring::manifest::write_manifest;

#[test]
fn manifest_is_ordered_and_excludes_its_own_output() {
    let directory = tempfile::tempdir().unwrap();
    let root = directory.path();
    fs::write(root.join("z.png"), b"sample image").unwrap();
    fs::create_dir(root.join("private")).unwrap();
    let records = root.join("private/answers.jsonl");
    fs::write(&records, b"{\"b\":2, \"a\":1}\n").unwrap();

    let first = write_manifest(root, None).unwrap();
    let first_contents = fs::read_to_string(root.join("manifest.json")).unwrap();
    assert!(!first_contents.contains("\"b\""));
    let second = write_manifest(root, None).unwrap();
    assert_eq!(first, second);
    assert_eq!(first.files.len(), 2);
    assert_eq!(first.files[0].path, "private/answers.jsonl");
    assert_eq!(first.files[1].path, "z.png");

    fs::write(&records, b"{\"a\":1,\"b\":2}\n").unwrap();
    let reordered = write_manifest(root, None).unwrap();
    assert_ne!(first.root_sha256, reordered.root_sha256);
    assert_eq!(
        first.files[0].record_sha256,
        reordered.files[0].record_sha256
    );
}

#[test]
fn fails_before_publishing_a_manifest_for_malformed_jsonl() {
    let directory = tempfile::tempdir().unwrap();
    fs::write(directory.path().join("answers.jsonl"), b"{malformed}\n").unwrap();
    assert!(write_manifest(directory.path(), None).is_err());
    assert!(!directory.path().join("manifest.json").exists());
}
