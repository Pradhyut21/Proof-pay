//! Fixed-point units and the public pump rules.
//!
//! INTERIM: this is the minimal oracle needed by the scaffold and the API (PP-03). PP-08 owns the
//! full independent typed-rule engine; both are checked against `shared/golden/pump_rules.json`.

use serde::Deserialize;
use std::collections::BTreeMap;

pub const SCHEMA_VERSION: &str = "1.0.0";
/// 300 kPa threshold expressed in milli-kPa.
pub const THRESHOLD_MKPA: i64 = 300_000;
const UNITS_JSON: &str = include_str!("../../../shared/units.json");

#[derive(Debug, Deserialize)]
struct UnitFactor {
    num: i128,
    den: i128,
}

#[derive(Debug, Deserialize)]
struct UnitTable {
    units: BTreeMap<String, UnitFactor>,
}

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum State {
    Stopped,
    Normal,
    LowPressure,
}

impl State {
    pub fn as_str(self) -> &'static str {
        match self {
            State::Stopped => "STOPPED",
            State::Normal => "NORMAL",
            State::LowPressure => "LOW_PRESSURE",
        }
    }
}

#[derive(Debug, PartialEq, Eq)]
pub enum UnitError {
    Unknown(String),
}

fn table() -> UnitTable {
    serde_json::from_str(UNITS_JSON).expect("shared/units.json is valid")
}

/// Round `num/den` to nearest, ties away from zero.
fn round_half_away(num: i128, den: i128) -> i128 {
    let (n, d) = if den < 0 { (-num, -den) } else { (num, den) };
    let q = (n.abs() * 2 + d) / (d * 2);
    if n >= 0 {
        q
    } else {
        -q
    }
}

/// Convert fixed-point thousandths between supported units.
pub fn convert_milli(value_milli: i64, from: &str, to: &str) -> Result<i64, UnitError> {
    let t = table();
    let f = t
        .units
        .get(from)
        .ok_or_else(|| UnitError::Unknown(from.into()))?;
    let g = t
        .units
        .get(to)
        .ok_or_else(|| UnitError::Unknown(to.into()))?;
    let num = value_milli as i128 * f.num * g.den;
    let den = f.den * g.num;
    Ok(round_half_away(num, den) as i64)
}

pub fn to_milli_kpa(value_milli: i64, unit: &str) -> Result<i64, UnitError> {
    convert_milli(value_milli, unit, "kPa")
}

pub fn pump_state(run: bool, inlet_mkpa: i64, outlet_mkpa: i64) -> State {
    if !run {
        State::Stopped
    } else if outlet_mkpa - inlet_mkpa >= THRESHOLD_MKPA {
        State::Normal
    } else {
        State::LowPressure
    }
}

/// ALARM is expected on only in LOW_PRESSURE.
pub fn expected_alarm(state: State) -> bool {
    state == State::LowPressure
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn rounding_ties_away_from_zero() {
        assert_eq!(round_half_away(5, 2), 3);
        assert_eq!(round_half_away(-5, 2), -3);
        assert_eq!(round_half_away(4, 3), 1);
    }

    #[test]
    fn threshold_is_inclusive() {
        assert_eq!(pump_state(true, 200_000, 500_000), State::Normal);
        assert_eq!(pump_state(true, 200_001, 500_000), State::LowPressure);
    }

    #[test]
    fn unknown_unit_is_rejected() {
        assert_eq!(
            convert_milli(1, "furlong", "kPa"),
            Err(UnitError::Unknown("furlong".into()))
        );
    }
}
