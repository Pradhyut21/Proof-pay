use std::collections::BTreeMap;
use std::fs::File;
use std::io::{Cursor, Read};
use std::path::{Path, PathBuf};

use anyhow::{ensure, Context, Result};
use panelproof_scoring::Answer;
use serde::{de::DeserializeOwned, Deserialize, Serialize};
use serde_json::Value;
use sha2::{Digest, Sha256};

const MAX_RECORD_BYTES: usize = 16 * 1024 * 1024;
const MAX_IMAGE_BYTES: usize = 8 * 1024 * 1024;
const MAX_TASKS: usize = 4096;
const SCHEMA_VERSION: &str = "1.0.0";
const MAX_SAFE_INTEGER: u64 = 9_007_199_254_740_991;

#[derive(Clone, Deserialize, Serialize)]
#[serde(deny_unknown_fields)]
pub struct PublicTask {
    pub schema_version: String,
    pub task_id: String,
    pub image_path: String,
    pub question: String,
    pub public_rules: String,
    pub response_schema: Value,
}

#[derive(Deserialize, Serialize)]
#[serde(deny_unknown_fields)]
struct PrivateTask {
    schema_version: String,
    task_id: String,
    base_scene_id: String,
    group_id: String,
    variant_kind: VariantKind,
    split: Split,
    skill: Skill,
    difficulty: serde_json::Map<String, Value>,
    answer: Answer,
    tolerance_milli: Option<i64>,
    evidence_regions: Option<Vec<EvidenceRegion>>,
    solver_version: String,
    image_sha256: String,
    validation_status: ValidationStatus,
}

#[derive(Deserialize, Serialize, PartialEq)]
#[serde(rename_all = "snake_case")]
enum VariantKind {
    Original,
    Semantic,
    SemanticPreserve,
    Nonsemantic,
    EvidenceRemoved,
}

#[derive(Deserialize, Serialize, PartialEq)]
#[serde(rename_all = "snake_case")]
enum Split {
    Dev,
    TestFrozen,
    DiagnosticAbstain,
    RealSlice,
}

#[derive(Deserialize, Serialize)]
#[serde(rename_all = "snake_case")]
enum Skill {
    Reading,
    Conversion,
    Association,
    Difference,
    OperationalState,
    IndicatorConsistency,
}

#[derive(Deserialize, Serialize, PartialEq)]
#[serde(rename_all = "snake_case")]
enum ValidationStatus {
    Pending,
    Accepted,
    Rejected,
}

#[derive(Clone, Deserialize, Serialize)]
#[serde(deny_unknown_fields)]
pub struct EvidenceRegion {
    instrument_id: String,
    x: u32,
    y: u32,
    width: u32,
    height: u32,
}

pub(crate) struct Task {
    pub public: PublicTask,
    private: PrivateTask,
    image_path: PathBuf,
    pub fingerprint: String,
}

impl Task {
    pub fn read_image(&self) -> Result<Vec<u8>> {
        ensure!(
            self.image_path.canonicalize()? == self.image_path,
            "image path changed"
        );
        checked_image(&self.image_path, &self.private.image_sha256)
    }

    pub fn supports_demo(&self) -> bool {
        self.private.split == Split::Dev
    }

    pub fn answer(&self) -> &Answer {
        &self.private.answer
    }

    pub fn tolerance_milli(&self) -> Option<i64> {
        self.private.tolerance_milli
    }

    pub fn evidence(&self) -> Option<&[EvidenceRegion]> {
        self.private.evidence_regions.as_deref()
    }

    pub fn solver_version(&self) -> &str {
        &self.private.solver_version
    }
}

pub(crate) fn valid_id(id: &str) -> bool {
    let bytes = id.as_bytes();
    (1..=80).contains(&bytes.len())
        && bytes[0].is_ascii_alphanumeric()
        && bytes
            .iter()
            .all(|b| b.is_ascii_alphanumeric() || *b == b'_' || *b == b'-')
}

fn valid_label(value: &str) -> bool {
    (1..=160).contains(&value.chars().count())
}

pub(crate) fn valid_answer(answer: &Answer) -> bool {
    match answer {
        Answer::Category { value } => valid_label(value),
        Answer::Numeric { value_milli, .. } => value_milli.unsigned_abs() <= MAX_SAFE_INTEGER,
        Answer::Set { values } => {
            let unique = values.iter().collect::<std::collections::BTreeSet<_>>();
            values.len() <= 32
                && unique.len() == values.len()
                && values.iter().all(|v| valid_label(v))
        }
    }
}

fn read_limited(path: &Path, limit: usize) -> Result<Vec<u8>> {
    let file = File::open(path)?;
    ensure!(file.metadata()?.is_file(), "expected a regular file");
    let mut bytes = Vec::new();
    file.take(limit as u64 + 1).read_to_end(&mut bytes)?;
    ensure!(bytes.len() <= limit, "artifact exceeds its size limit");
    Ok(bytes)
}

fn json_lines<T: DeserializeOwned>(root: &Path, name: &str) -> Result<Vec<T>> {
    let path = root
        .join(name)
        .canonicalize()
        .with_context(|| format!("missing {name}"))?;
    ensure!(
        path.starts_with(root),
        "record file must stay in the dataset"
    );
    let records = read_limited(&path, MAX_RECORD_BYTES)?;
    let records = std::str::from_utf8(&records)?;
    records
        .lines()
        .enumerate()
        .filter(|(_, row)| !row.trim().is_empty())
        .take(MAX_TASKS + 1)
        .map(|(line, row)| {
            serde_json::from_str(row)
                .with_context(|| format!("invalid {name} record on line {}", line + 1))
        })
        .collect()
}

fn checked_image(path: &Path, expected_hash: &str) -> Result<Vec<u8>> {
    let bytes = read_limited(path, MAX_IMAGE_BYTES)?;
    ensure!(
        format!("{:x}", Sha256::digest(&bytes)) == expected_hash,
        "PNG hash mismatch"
    );
    Ok(bytes)
}

fn inspect_png(bytes: &[u8]) -> Result<(u32, u32)> {
    ensure!(
        bytes.len() >= 33 && &bytes[..16] == b"\x89PNG\r\n\x1a\n\0\0\0\rIHDR",
        "invalid PNG header"
    );
    let width = u32::from_be_bytes(bytes[16..20].try_into()?);
    let height = u32::from_be_bytes(bytes[20..24].try_into()?);
    ensure!(
        (1..=4096).contains(&width) && (1..=4096).contains(&height),
        "PNG dimensions outside allowed range"
    );
    let mut remaining = &bytes[8..];
    loop {
        ensure!(remaining.len() >= 12, "truncated PNG chunk");
        let length = u32::from_be_bytes(remaining[..4].try_into()?) as usize;
        let kind = &remaining[4..8];
        ensure!(
            matches!(kind, b"IHDR" | b"PLTE" | b"IDAT" | b"IEND" | b"tRNS"),
            "PNG contains metadata or unsupported chunks"
        );
        ensure!(length <= remaining.len() - 12, "truncated PNG chunk");
        remaining = &remaining[length + 12..];
        if kind == b"IEND" {
            ensure!(length == 0 && remaining.is_empty(), "invalid PNG ending");
            break;
        }
    }
    let mut png = png::Decoder::new(Cursor::new(bytes)).read_info()?;
    let capacity = png
        .output_buffer_size()
        .context("PNG output size overflow")?;
    ensure!(
        capacity <= 64 * 1024 * 1024,
        "decoded PNG exceeds its size limit"
    );
    png.next_frame(&mut vec![0; capacity])?;
    png.finish()?;
    Ok((width, height))
}

pub(crate) fn load_tasks(root: &Path) -> Result<BTreeMap<String, Task>> {
    let root = root.canonicalize()?;
    let public: Vec<PublicTask> = json_lines(&root, "public/tasks.jsonl")?;
    let private: Vec<PrivateTask> = json_lines(&root, "private/tasks.jsonl")?;
    ensure!(
        !public.is_empty() && public.len() == private.len() && public.len() <= MAX_TASKS,
        "public and private task counts must match within the dataset limit"
    );
    let mut private_by_id = BTreeMap::new();
    let mut benchmark_splits = BTreeMap::new();
    for record in private {
        if matches!(record.split, Split::Dev | Split::TestFrozen) {
            let frozen = record.split == Split::TestFrozen;
            for (field, value) in [
                ("base_scene_id", &record.base_scene_id),
                ("group_id", &record.group_id),
                ("image_sha256", &record.image_sha256),
            ] {
                let previous = benchmark_splits.insert((field, value.clone()), frozen);
                ensure!(
                    previous.is_none_or(|prior| prior == frozen),
                    "dev and frozen tasks share {field}"
                );
            }
        }
        ensure!(
            private_by_id
                .insert(record.task_id.clone(), record)
                .is_none(),
            "duplicate private task ID"
        );
    }
    let mut tasks = BTreeMap::new();
    for public in public {
        let id = public.task_id.clone();
        let private = private_by_id
            .remove(&id)
            .context("missing corresponding private record or duplicate public task")?;
        ensure!(
            public.schema_version == SCHEMA_VERSION
                && private.schema_version == SCHEMA_VERSION
                && valid_id(&id)
                && valid_id(&private.base_scene_id)
                && valid_id(&private.group_id),
            "invalid task version or identifiers"
        );
        ensure!(
            (1..=4096).contains(&public.question.chars().count())
                && (1..=4096).contains(&public.public_rules.chars().count())
                && public.response_schema.is_object(),
            "invalid public question, rule or response schema"
        );
        ensure!(
            private.validation_status == ValidationStatus::Accepted,
            "only accepted task artifacts can be imported"
        );
        ensure!(
            valid_label(&private.solver_version)
                && valid_answer(&private.answer)
                && private.tolerance_milli.is_none_or(|value| value >= 0
                    && value.unsigned_abs() <= MAX_SAFE_INTEGER
                    && matches!(private.answer, Answer::Numeric { .. })),
            "invalid reference answer, tolerance or solver version"
        );
        ensure!(
            private.variant_kind != VariantKind::EvidenceRemoved
                || private.split == Split::DiagnosticAbstain,
            "missing-evidence artifacts belong to the separate diagnostic split"
        );
        let image_id = public
            .image_path
            .strip_prefix("images/")
            .and_then(|path| path.strip_suffix(".png"))
            .context("task image must use images/<id>.png")?;
        ensure!(valid_id(image_id), "invalid image identifier");
        let image_path = root.join(&public.image_path).canonicalize()?;
        ensure!(
            image_path.starts_with(root.join("images")),
            "image path resolves outside the image directory"
        );
        let (width, height) = inspect_png(&checked_image(&image_path, &private.image_sha256)?)?;
        if let Some(regions) = &private.evidence_regions {
            ensure!(
                regions.iter().all(|r| valid_id(&r.instrument_id)
                    && r.width > 0
                    && r.height > 0
                    && r.x.checked_add(r.width).is_some_and(|x| x <= width)
                    && r.y.checked_add(r.height).is_some_and(|y| y <= height)),
                "evidence region outside image"
            );
        }
        let fingerprint = format!(
            "{:x}",
            Sha256::digest(serde_json::to_vec(&(&public, &private))?)
        );
        tasks.insert(
            id,
            Task {
                public,
                private,
                image_path,
                fingerprint,
            },
        );
    }
    Ok(tasks)
}
