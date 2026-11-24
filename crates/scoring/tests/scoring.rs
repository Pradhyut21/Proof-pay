use panelproof_oracle::PressureUnit;
use panelproof_scoring::{answers_match, score, Answer, Outcome, Prediction, Reference};

fn category(value: &str) -> Answer {
    Answer::Category {
        value: value.into(),
    }
}

fn numeric(value_milli: i64, unit: PressureUnit) -> Answer {
    Answer::Numeric { value_milli, unit }
}

fn reference(id: &str, kind: &str, answer: &str) -> Reference {
    Reference {
        task_id: id.into(),
        answer: category(answer),
        tolerance_milli: None,
        group_id: Some("g1".into()),
        pair_id: None,
        variant_kind: Some(kind.into()),
    }
}

#[test]
fn scores_reference_tolerance_and_unordered_sets() {
    let answer = numeric(3_000, PressureUnit::Bar);
    let at_boundary = numeric(300_100, PressureUnit::Kpa);
    let outside_boundary = numeric(300_101, PressureUnit::Kpa);
    assert!(answers_match(&answer, &at_boundary, Some(1)).unwrap());
    assert!(!answers_match(&answer, &outside_boundary, Some(1)).unwrap());
    assert!(answers_match(&answer, &at_boundary, Some(-1)).is_err());

    let set_ab = Answer::Set {
        values: vec!["A".into(), "B".into()],
    };
    let set_ba = Answer::Set {
        values: vec!["B".into(), "A".into()],
    };
    assert!(answers_match(&set_ab, &set_ba, None).unwrap());
    let duplicated = Answer::Set {
        values: vec!["A".into(), "A".into()],
    };
    assert!(answers_match(&set_ab, &duplicated, None).is_err());
}

#[test]
fn separates_missing_predictions_from_incorrect_and_checks_pairs() {
    let references = [
        reference("a", "original", "NORMAL"),
        reference("b", "semantic_flip", "LOW_PRESSURE"),
        reference("c", "nuisance", "NORMAL"),
        reference("d", "nuisance", "NORMAL"),
    ];
    let predictions = [
        Prediction {
            task_id: "a".into(),
            answer: Some(category("NORMAL")),
        },
        Prediction {
            task_id: "b".into(),
            answer: Some(category("LOW_PRESSURE")),
        },
        Prediction {
            task_id: "c".into(),
            answer: Some(category("LOW_PRESSURE")),
        },
    ];
    let report = score(&references, &predictions).unwrap();
    assert_eq!(report.valid, 3);
    assert_eq!(report.correct, 2);
    assert_eq!(report.incorrect, 1);
    assert_eq!(report.missing, 1);
    assert_eq!(report.tasks[3].outcome, Outcome::Missing);
    assert_eq!(report.accuracy_valid_only, Some(2.0 / 3.0));
    assert_eq!(report.accuracy_all_references, Some(0.5));
    assert_eq!(report.semantic_pairs.both_correct, 1);
    assert_eq!(report.semantic_pairs.changed, 1);
    assert_eq!(report.nuisance_pairs.pairs, 2);
    assert_eq!(report.nuisance_pairs.valid_pairs, 1);
    assert_eq!(report.nuisance_pairs.unchanged, 0);
    assert_eq!(report.worst_group_accuracy, Some(0.0));
}

#[test]
fn ambiguous_group_pairs_require_an_explicit_pair_identity() {
    let mut references = [
        reference("a", "original", "NORMAL"),
        reference("b", "original", "NORMAL"),
        reference("c", "semantic_flip", "LOW_PRESSURE"),
    ];
    let report = score(&references, &[]).unwrap();
    assert_eq!(report.semantic_pairs.pairs, 0);
    assert_eq!(report.groups_with_ambiguous_pairing, 1);
    references[0].pair_id = Some("p1".into());
    references[2].pair_id = Some("p1".into());
    let report = score(&references, &[]).unwrap();
    assert_eq!(report.semantic_pairs.pairs, 1);
    assert_eq!(report.groups_with_ambiguous_pairing, 0);
}

#[test]
fn rejects_unknown_and_duplicate_prediction_records() {
    let references = [reference("a", "original", "NORMAL")];
    let unknown = Prediction {
        task_id: "b".into(),
        answer: None,
    };
    let duplicated = Prediction {
        task_id: "a".into(),
        answer: None,
    };
    assert!(score(&references, &[unknown]).is_err());
    assert!(score(&references, &[duplicated.clone(), duplicated]).is_err());
}
