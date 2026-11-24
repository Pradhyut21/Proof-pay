use std::fs;
use std::io::Write;
use std::path::{Component, Path, PathBuf};

use anyhow::{bail, Context, Result};
use panelproof_oracle::SCHEMA_VERSION;
use serde::Serialize;
use sha2::{Digest, Sha256};

#[derive(Debug, PartialEq, Eq, Serialize)]
pub struct FileEntry {
    pub path: String,
    pub bytes: u64,
    pub sha256: String,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub record_sha256: Option<Vec<String>>,
}

#[derive(Debug, PartialEq, Eq, Serialize)]
pub struct Manifest {
    pub schema_version: &'static str,
    pub root_sha256: String,
    pub files: Vec<FileEntry>,
}

fn sha256(bytes: &[u8]) -> String {
    format!("{:x}", Sha256::digest(bytes))
}

fn normalized_path(path: &Path) -> Result<String> {
    let components: Vec<_> = path
        .components()
        .map(|component| match component {
            Component::Normal(part) => part
                .to_str()
                .filter(|part| !part.contains('\\'))
                .context("manifest paths must use portable UTF-8 components"),
            _ => bail!("manifest paths must be relative to the selected directory"),
        })
        .collect::<Result<_>>()?;
    Ok(components.join("/"))
}

fn visit(
    root: &Path,
    directory: &Path,
    exclude: &Path,
    paths: &mut Vec<(String, PathBuf)>,
) -> Result<()> {
    for entry in fs::read_dir(directory).with_context(|| format!("read {}", directory.display()))? {
        let entry = entry?;
        let path = entry.path();
        let file_type = entry.file_type()?;
        if file_type.is_symlink() {
            bail!("symlinks are not allowed in a manifest: {}", path.display());
        }
        if path == exclude {
            if !file_type.is_file() {
                bail!("manifest output is not a regular file: {}", path.display());
            }
        } else if file_type.is_dir() {
            visit(root, &path, exclude, paths)?;
        } else if file_type.is_file() {
            let relative = normalized_path(path.strip_prefix(root)?)?;
            paths.push((relative, path));
        } else {
            bail!("unsupported file type: {}", path.display());
        }
    }
    Ok(())
}

fn jsonl_record_hashes(bytes: &[u8], path: &Path) -> Result<Vec<String>> {
    std::str::from_utf8(bytes)
        .with_context(|| format!("read UTF-8 JSONL {}", path.display()))?
        .lines()
        .enumerate()
        .filter(|(_, line)| !line.trim().is_empty())
        .map(|(index, line)| {
            let mut record: serde_json::Value = serde_json::from_str(line)
                .with_context(|| format!("parse {} line {}", path.display(), index + 1))?;
            record.sort_all_objects();
            Ok(sha256(&serde_json::to_vec(&record)?))
        })
        .collect()
}

/// Scan a frozen dataset directory, then atomically persist its manifest.
/// The manifest is excluded from its own hash, including on repeated runs.
pub fn write_manifest(directory: &Path, output: Option<&Path>) -> Result<Manifest> {
    let root = directory
        .canonicalize()
        .with_context(|| format!("resolve {}", directory.display()))?;
    let default_output = root.join("manifest.json");
    let output = output.unwrap_or(&default_output);
    let filename = output
        .file_name()
        .context("manifest output is a directory")?;
    let parent = output
        .parent()
        .filter(|parent| !parent.as_os_str().is_empty())
        .unwrap_or_else(|| Path::new("."))
        .canonicalize()
        .with_context(|| format!("resolve the parent of {}", output.display()))?;
    let output = parent.join(filename);
    if fs::symlink_metadata(&output).is_ok_and(|metadata| !metadata.is_file()) {
        bail!(
            "manifest output is not a regular file: {}",
            output.display()
        );
    }

    let mut paths = Vec::new();
    visit(&root, &root, &output, &mut paths)?;
    paths.sort_unstable_by(|first, second| first.0.cmp(&second.0));
    let mut files = Vec::with_capacity(paths.len());
    for (relative, path) in paths {
        let contents = fs::read(&path).with_context(|| format!("read {}", path.display()))?;
        let record_sha256 = relative
            .ends_with(".jsonl")
            .then(|| jsonl_record_hashes(&contents, &path))
            .transpose()?;
        files.push(FileEntry {
            path: relative,
            bytes: contents.len() as u64,
            sha256: sha256(&contents),
            record_sha256,
        });
    }

    let manifest = Manifest {
        schema_version: SCHEMA_VERSION,
        root_sha256: sha256(&serde_json::to_vec(&(SCHEMA_VERSION, &files))?),
        files,
    };
    let mut temporary = tempfile::NamedTempFile::new_in(parent)?;
    serde_json::to_writer_pretty(&mut temporary, &manifest)?;
    temporary.write_all(b"\n")?;
    temporary
        .persist(&output)
        .with_context(|| format!("publish {}", output.display()))?;
    Ok(manifest)
}
