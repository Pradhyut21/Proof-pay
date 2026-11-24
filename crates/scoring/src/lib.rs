//! Exact enum scoring and unit-aware numeric tolerance scoring.

use serde_json::Value;

#[derive(Debug, Clone, Copy, PartialEq, Eq, serde::Serialize)]
#[serde(rename_all = "lowercase")]
pub enum Outcome {
    Correct,
    Incorrect,
    Invalid,
}

impl Outcome {
    pub fn as_str(self) -> &'static str {
        match self {
            Outcome::Correct => "correct",
            Outcome::Incorrect => "incorrect",
            Outcome::Invalid => "invalid",
        }
    }
}

/// Score a response against the private reference answer.
///
/// * category: exact string match, wrong kind is `Invalid`
/// * numeric: unit must match exactly and `value_milli` must be an integer within the inclusive
///   tolerance; otherwise `Invalid` (unit/format) or `Incorrect` (out of tolerance)
pub fn score(answer: &Value, response: &Value) -> Outcome {
    if response.is_null() || response.get("kind") != answer.get("kind") {
        return Outcome::Invalid;
    }
    match answer["kind"].as_str() {
        Some("category") => match (answer["value"].as_str(), response["value"].as_str()) {
            (Some(a), Some(r)) if a == r => Outcome::Correct,
            (_, Some(_)) => Outcome::Incorrect,
            _ => Outcome::Invalid,
        },
        Some("numeric") => {
            if answer["unit"] != response["unit"] {
                return Outcome::Invalid;
            }
            let (Some(a), Some(r), Some(t)) = (
                answer["value_milli"].as_i64(),
                response["value_milli"].as_i64(),
                answer["tolerance_milli"].as_i64(),
            ) else {
                return Outcome::Invalid;
            };
            if (r - a).abs() <= t {
                Outcome::Correct
            } else {
                Outcome::Incorrect
            }
        }
        _ => Outcome::Invalid,
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use serde_json::json;

    #[test]
    fn tolerance_is_inclusive() {
        let a = json!({"kind":"numeric","value_milli":100,"unit":"bar","tolerance_milli":5});
        let r = |v: i64| json!({"kind":"numeric","value_milli":v,"unit":"bar"});
        assert_eq!(score(&a, &r(105)), Outcome::Correct);
        assert_eq!(score(&a, &r(106)), Outcome::Incorrect);
        let bad = json!({"kind":"numeric","value_milli":1.5,"unit":"bar"});
        assert_eq!(score(&a, &bad), Outcome::Invalid);
    }
}
