use std::collections::{BTreeMap, BTreeSet};

use panelproof_oracle::{
    convert_to_milli_kpa, is_identifier, is_label, OracleError, Pressure, PressureUnit,
    MAX_SAFE_INTEGER,
};
use serde::{Deserialize, Serialize};
use thiserror::Error;

pub mod manifest;

#[derive(Clone, Debug, Deserialize, PartialEq, Eq, Serialize)]
#[serde(tag = "kind", rename_all = "snake_case", deny_unknown_fields)]
pub enum Answer {
    Category {
        value: String,
    },
    Numeric {
        value_milli: i64,
        unit: PressureUnit,
    },
    Set {
        values: Vec<String>,
    },
}

#[derive(Clone, Debug, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct Reference {
    pub task_id: String,
    pub answer: Answer,
    pub tolerance_milli: Option<i64>,
    pub group_id: Option<String>,
    pub pair_id: Option<String>,
    pub variant_kind: Option<String>,
}

#[derive(Clone, Debug, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct Prediction {
    pub task_id: String,
    pub answer: Option<Answer>,
}

#[derive(Clone, Copy, Debug, PartialEq, Eq, Serialize)]
#[serde(rename_all = "snake_case")]
pub enum Outcome {
    Correct,
    Incorrect,
    Missing,
}

#[derive(Debug, Serialize)]
pub struct TaskOutcome {
    pub task_id: String,
    pub outcome: Outcome,
}

#[derive(Default, Debug, Serialize)]
pub struct PairCounts {
    pub pairs: usize,
    pub valid_pairs: usize,
    pub both_correct: usize,
    pub unchanged: usize,
    pub changed: usize,
}

impl PairCounts {
    fn record(
        &mut self,
        base: &ScoredTask<'_>,
        variant: &ScoredTask<'_>,
    ) -> Result<(), ScoreError> {
        self.pairs += 1;
        if let (Some(first), Some(second)) = (base.prediction, variant.prediction) {
            self.valid_pairs += 1;
            if answers_match(first, second, None)? {
                self.unchanged += 1;
            } else {
                self.changed += 1;
            }
        }
        if base.outcome == Outcome::Correct && variant.outcome == Outcome::Correct {
            self.both_correct += 1;
        }
        Ok(())
    }
}

#[derive(Debug, Serialize)]
pub struct ScoreReport {
    pub references: usize,
    pub prediction_records: usize,
    pub valid: usize,
    pub missing: usize,
    pub correct: usize,
    pub incorrect: usize,
    pub accuracy_valid_only: Option<f64>,
    pub accuracy_all_references: Option<f64>,
    pub groups: usize,
    pub groups_all_correct: usize,
    pub worst_group_accuracy: Option<f64>,
    pub semantic_pairs: PairCounts,
    pub nuisance_pairs: PairCounts,
    pub groups_with_ambiguous_pairing: usize,
    pub tasks: Vec<TaskOutcome>,
}

#[derive(Debug, Error)]
pub enum ScoreError {
    #[error("invalid answer: {0}")]
    InvalidAnswer(&'static str),
    #[error("numeric tolerance must be a nonnegative safe integer on a numeric reference")]
    InvalidTolerance,
    #[error("invalid task ID {0:?}")]
    InvalidTaskId(String),
    #[error("duplicate reference for task {0}")]
    DuplicateReference(String),
    #[error("duplicate prediction for task {0}")]
    DuplicatePrediction(String),
    #[error("prediction for unknown task {0}")]
    UnknownTask(String),
    #[error(transparent)]
    Conversion(#[from] OracleError),
}

fn validate_answer(answer: &Answer) -> Result<(), ScoreError> {
    match answer {
        Answer::Category { value } if !is_label(value) => Err(ScoreError::InvalidAnswer(
            "category must contain 1 to 160 characters",
        )),
        Answer::Set { values }
            if values.len() > 32
                || values.iter().any(|value| !is_label(value))
                || values.iter().collect::<BTreeSet<_>>().len() != values.len() =>
        {
            Err(ScoreError::InvalidAnswer(
                "set exceeds 32 items or contains an invalid member",
            ))
        }
        Answer::Numeric { value_milli, .. }
            if !(-MAX_SAFE_INTEGER..=MAX_SAFE_INTEGER).contains(value_milli) =>
        {
            Err(ScoreError::InvalidAnswer(
                "value is outside the safe integer range",
            ))
        }
        _ => Ok(()),
    }
}

/// Compare numeric readings in reference display units when the units match,
/// or after the shared canonical milli-kPa conversion for mixed pressure units.
pub fn answers_match(
    reference: &Answer,
    prediction: &Answer,
    tolerance_milli: Option<i64>,
) -> Result<bool, ScoreError> {
    validate_answer(reference)?;
    validate_answer(prediction)?;
    let tolerance = tolerance_milli.unwrap_or(0);
    if !(0..=MAX_SAFE_INTEGER).contains(&tolerance)
        || (tolerance_milli.is_some() && !matches!(reference, Answer::Numeric { .. }))
    {
        return Err(ScoreError::InvalidTolerance);
    }
    match (reference, prediction) {
        (Answer::Category { value: first }, Answer::Category { value: second }) => {
            Ok(first == second)
        }
        (Answer::Set { values: first }, Answer::Set { values: second }) => {
            Ok(first.iter().collect::<BTreeSet<_>>() == second.iter().collect::<BTreeSet<_>>())
        }
        (
            Answer::Numeric {
                value_milli: first,
                unit: first_unit,
            },
            Answer::Numeric {
                value_milli: second,
                unit: second_unit,
            },
        ) => {
            if first_unit == second_unit {
                return Ok(first.abs_diff(*second) <= tolerance as u64);
            }
            let convert = |value_milli, unit| convert_to_milli_kpa(Pressure { value_milli, unit });
            let first = convert(*first, *first_unit)?;
            let second = convert(*second, *second_unit)?;
            let tolerance = convert(tolerance, *first_unit)?;
            Ok(first.abs_diff(second) <= tolerance as u64)
        }
        _ => Ok(false),
    }
}

struct ScoredTask<'a> {
    reference: &'a Reference,
    prediction: Option<&'a Answer>,
    outcome: Outcome,
}

fn ratio(numerator: usize, denominator: usize) -> Option<f64> {
    (denominator > 0).then(|| numerator as f64 / denominator as f64)
}

fn is_original(kind: Option<&str>) -> bool {
    matches!(kind, Some("original" | "base"))
}

/// Score a single evaluation condition. Compare variants through an explicit
/// pair ID when supplied, or a group with just one original otherwise.
pub fn score(
    references: &[Reference],
    predictions: &[Prediction],
) -> Result<ScoreReport, ScoreError> {
    let mut by_id = BTreeMap::new();
    for reference in references {
        if !is_identifier(&reference.task_id) {
            return Err(ScoreError::InvalidTaskId(reference.task_id.clone()));
        }
        answers_match(
            &reference.answer,
            &reference.answer,
            reference.tolerance_milli,
        )?;
        if by_id.insert(&reference.task_id, reference).is_some() {
            return Err(ScoreError::DuplicateReference(reference.task_id.clone()));
        }
    }
    let mut predicted = BTreeMap::new();
    for prediction in predictions {
        if !by_id.contains_key(&prediction.task_id) {
            return Err(ScoreError::UnknownTask(prediction.task_id.clone()));
        }
        if predicted
            .insert(&prediction.task_id, prediction.answer.as_ref())
            .is_some()
        {
            return Err(ScoreError::DuplicatePrediction(prediction.task_id.clone()));
        }
    }

    let mut tasks = Vec::with_capacity(references.len());
    for reference in by_id.values().copied() {
        let prediction = predicted.get(&reference.task_id).copied().flatten();
        let outcome = match prediction {
            None => Outcome::Missing,
            Some(answer)
                if answers_match(&reference.answer, answer, reference.tolerance_milli)? =>
            {
                Outcome::Correct
            }
            Some(_) => Outcome::Incorrect,
        };
        tasks.push(ScoredTask {
            reference,
            prediction,
            outcome,
        });
    }

    let mut groups = BTreeMap::new();
    let mut pair_groups: BTreeMap<(bool, &str), Vec<&ScoredTask<'_>>> = BTreeMap::new();
    let mut correct = 0;
    let mut incorrect = 0;
    for task in &tasks {
        correct += usize::from(task.outcome == Outcome::Correct);
        incorrect += usize::from(task.outcome == Outcome::Incorrect);
        let reference = task.reference;
        if let Some(group) = reference.group_id.as_deref() {
            let group_correct = groups.entry(group).or_insert(true);
            *group_correct &= task.outcome == Outcome::Correct;
        }
        let pair_key = reference
            .pair_id
            .as_deref()
            .map(|id| (true, id))
            .or_else(|| reference.group_id.as_deref().map(|id| (false, id)));
        if let Some(key) = pair_key {
            pair_groups.entry(key).or_default().push(task);
        }
    }

    let mut semantic_pairs = PairCounts::default();
    let mut nuisance_pairs = PairCounts::default();
    let mut groups_with_ambiguous_pairing = 0;
    for members in pair_groups.values() {
        let mut originals = members
            .iter()
            .filter(|task| is_original(task.reference.variant_kind.as_deref()));
        let variants = members.iter().filter_map(|task| {
            let metric = match task.reference.variant_kind.as_deref() {
                Some("semantic" | "semantic_flip") => true,
                Some("nonsemantic" | "nuisance" | "semantic_preserve") => false,
                _ => return None,
            };
            Some((task, metric))
        });
        match (originals.next(), originals.next()) {
            (Some(base), None) => {
                for (variant, semantic) in variants {
                    let counters = if semantic {
                        &mut semantic_pairs
                    } else {
                        &mut nuisance_pairs
                    };
                    counters.record(base, variant)?;
                }
            }
            _ if variants.count() > 0 => groups_with_ambiguous_pairing += 1,
            _ => {}
        }
    }
    let total = references.len();
    let valid = correct + incorrect;
    let groups_all_correct = groups.values().filter(|&&value| value).count();
    Ok(ScoreReport {
        references: total,
        prediction_records: predictions.len(),
        valid,
        missing: total - valid,
        correct,
        incorrect,
        accuracy_valid_only: ratio(correct, valid),
        accuracy_all_references: ratio(correct, total),
        groups: groups.len(),
        groups_all_correct,
        worst_group_accuracy: ratio(groups_all_correct, groups.len()),
        semantic_pairs,
        nuisance_pairs,
        groups_with_ambiguous_pairing,
        tasks: tasks
            .into_iter()
            .map(|task| TaskOutcome {
                task_id: task.reference.task_id.clone(),
                outcome: task.outcome,
            })
            .collect(),
    })
}
