use std::fs::File;
use std::io::{self, BufRead, BufReader, BufWriter, Write};
use std::path::{Path, PathBuf};

use anyhow::{bail, Context, Result};
use clap::{Parser, Subcommand, ValueEnum};
use panelproof_oracle::{verify_scene_with_rule, PumpRule, Scene};
use panelproof_scoring::{manifest::write_manifest, score, Prediction, Reference};
use serde::de::DeserializeOwned;

#[derive(Parser)]
#[command(
    version,
    about = "PanelProof independent rule verifier, scorer and dataset manifest"
)]
struct Arguments {
    #[command(subcommand)]
    command: Command,
}

#[derive(Clone, Copy, ValueEnum)]
enum VerifyRule {
    Delta,
    InletFloor,
}

#[derive(Subcommand)]
enum Command {
    /// Verify rule outcomes independently for JSONL scene records.
    Verify {
        /// Scene JSONL file or '-' for stdin.
        #[arg(long)]
        scenes: PathBuf,
        /// Pump rule used for all scenes in this request.
        #[arg(long, value_enum, default_value = "delta")]
        rule: VerifyRule,
    },
    /// Score a single matched condition against private reference records.
    Score {
        /// Reference JSONL file or '-' for stdin.
        #[arg(long)]
        refs: PathBuf,
        /// Prediction JSONL file or '-' for stdin.
        #[arg(long)]
        preds: PathBuf,
    },
    /// Write a sorted SHA-256 manifest for a frozen dataset directory.
    Manifest {
        #[arg(long)]
        dir: PathBuf,
        /// Defaults to manifest.json inside the input directory.
        #[arg(long)]
        output: Option<PathBuf>,
    },
}

fn read_jsonl<T: DeserializeOwned>(path: &Path) -> Result<Vec<T>> {
    let reader: Box<dyn BufRead> = if path == Path::new("-") {
        Box::new(io::stdin().lock())
    } else {
        Box::new(BufReader::new(
            File::open(path).with_context(|| format!("open {}", path.display()))?,
        ))
    };
    let mut records = Vec::new();
    for (index, line) in reader.lines().enumerate() {
        let context = || format!("read {} line {}", path.display(), index + 1);
        let line = line.with_context(context)?;
        if !line.trim().is_empty() {
            records.push(serde_json::from_str(&line).with_context(context)?);
        }
    }
    Ok(records)
}

fn json_line(writer: &mut impl Write, data: &impl serde::Serialize) -> Result<()> {
    serde_json::to_writer(&mut *writer, data)?;
    writer.write_all(b"\n")?;
    Ok(())
}

fn main() -> Result<()> {
    let args = Arguments::parse();
    let mut stdout = BufWriter::new(io::stdout().lock());
    match args.command {
        Command::Verify { scenes, rule } => {
            let rule = match rule {
                VerifyRule::Delta => PumpRule::Delta,
                VerifyRule::InletFloor => PumpRule::InletFloor,
            };
            let scenes = read_jsonl::<Scene>(&scenes)?;
            for scene in scenes {
                let verified = verify_scene_with_rule(&scene, rule)
                    .with_context(|| format!("verify scene {}", scene.base_scene_id))?;
                json_line(&mut stdout, &verified)?;
            }
        }
        Command::Score { refs, preds } => {
            if refs == Path::new("-") && preds == Path::new("-") {
                bail!("at most one of --refs and --preds can read stdin");
            }
            let references = read_jsonl::<Reference>(&refs)?;
            let predictions = read_jsonl::<Prediction>(&preds)?;
            json_line(&mut stdout, &score(&references, &predictions)?)?;
        }
        Command::Manifest { dir, output } => {
            json_line(&mut stdout, &write_manifest(&dir, output.as_deref())?)?;
        }
    }
    stdout.flush()?;
    Ok(())
}
