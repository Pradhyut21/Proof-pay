use std::collections::HashMap;
use std::sync::OnceLock;

use serde::{Deserialize, Serialize};
use thiserror::Error;

pub const SCHEMA_VERSION: &str = "1.0.0";
pub const MAX_SAFE_INTEGER: i64 = 9_007_199_254_740_991;
pub const NORMAL_DELTA_MILLI_KPA: i64 = 300_000;
pub const NORMAL_INLET_MILLI_KPA: i64 = 150_000;

const UNITS_JSON: &str = include_str!("../../../shared/units.json");

#[derive(Clone, Copy, Debug, Deserialize, Eq, Hash, PartialEq, Serialize)]
pub enum PressureUnit {
    #[serde(rename = "kPa")]
    Kpa,
    #[serde(rename = "bar")]
    Bar,
    #[serde(rename = "psi")]
    Psi,
}

#[derive(Clone, Copy, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(deny_unknown_fields)]
pub struct Pressure {
    pub value_milli: i64,
    pub unit: PressureUnit,
}

#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(deny_unknown_fields)]
pub struct Equipment {
    pub id: String,
    pub label: String,
    pub inlet: Pressure,
    pub outlet: Pressure,
    pub run: bool,
    pub alarm: bool,
}

#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(deny_unknown_fields)]
pub struct Scene {
    pub schema_version: String,
    pub base_scene_id: String,
    pub seed: u64,
    pub layout_family: String,
    pub style_family: String,
    pub equipment: Vec<Equipment>,
}

#[derive(Clone, Copy, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(rename_all = "SCREAMING_SNAKE_CASE")]
pub enum PumpState {
    Stopped,
    Normal,
    LowPressure,
}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum PumpRule {
    Delta,
    InletFloor,
}

#[derive(Clone, Copy, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(rename_all = "SCREAMING_SNAKE_CASE")]
pub enum Consistency {
    Consistent,
    Contradiction,
}

#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
pub struct PumpVerification {
    pub id: String,
    pub inlet_milli_kpa: i64,
    pub outlet_milli_kpa: i64,
    pub delta_milli_kpa: i64,
    pub state: PumpState,
    pub consistency: Consistency,
}

#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
pub struct SceneVerification {
    pub base_scene_id: String,
    pub equipment: Vec<PumpVerification>,
}

#[derive(Debug, Error)]
pub enum OracleError {
    #[error("invalid embedded unit contract: {0}")]
    UnitContract(String),
    #[error("fixed-point value {0} is outside the cross-language safe range")]
    UnsafeInteger(i64),
    #[error("conversion result exceeds representable range")]
    ConversionOverflow,
    #[error("unsupported scene schema version {0}")]
    SchemaVersion(String),
    #[error("invalid scene: {0}")]
    InvalidScene(&'static str),
}

#[derive(Deserialize)]
struct Ratio {
    numerator: i64,
    denominator: i64,
}

#[derive(Deserialize)]
struct UnitContract {
    pressure: HashMap<PressureUnit, Ratio>,
}

static UNIT_CONTRACT: OnceLock<Result<UnitContract, String>> = OnceLock::new();

pub fn is_identifier(value: &str) -> bool {
    let bytes = value.as_bytes();
    bytes.len() <= 80
        && bytes.first().is_some_and(u8::is_ascii_alphanumeric)
        && bytes
            .iter()
            .all(|byte| byte.is_ascii_alphanumeric() || matches!(*byte, b'_' | b'-'))
}

pub fn is_label(value: &str) -> bool {
    !value.is_empty() && value.chars().count() <= 160
}

pub fn convert_to_milli_kpa(pressure: Pressure) -> Result<i64, OracleError> {
    if !(-MAX_SAFE_INTEGER..=MAX_SAFE_INTEGER).contains(&pressure.value_milli) {
        return Err(OracleError::UnsafeInteger(pressure.value_milli));
    }
    let contract = UNIT_CONTRACT
        .get_or_init(|| serde_json::from_str(UNITS_JSON).map_err(|error| error.to_string()))
        .as_ref()
        .map_err(|error| OracleError::UnitContract(error.clone()))?;
    let ratio = contract
        .pressure
        .get(&pressure.unit)
        .filter(|ratio| ratio.numerator > 0 && ratio.denominator > 0)
        .ok_or_else(|| {
            OracleError::UnitContract(format!("missing ratio for {:?}", pressure.unit))
        })?;
    let numerator = i128::from(pressure.value_milli) * i128::from(ratio.numerator);
    let denominator = i128::from(ratio.denominator);
    let rounded = (numerator.abs() + denominator / 2) / denominator;
    i64::try_from(rounded * numerator.signum()).map_err(|_| OracleError::ConversionOverflow)
}

pub fn verify_equipment(equipment: &Equipment) -> Result<PumpVerification, OracleError> {
    verify_equipment_with_rule(equipment, PumpRule::Delta)
}

pub fn verify_equipment_with_rule(
    equipment: &Equipment,
    rule: PumpRule,
) -> Result<PumpVerification, OracleError> {
    let inlet = convert_to_milli_kpa(equipment.inlet)?;
    let outlet = convert_to_milli_kpa(equipment.outlet)?;
    let delta = outlet
        .checked_sub(inlet)
        .ok_or(OracleError::ConversionOverflow)?;
    let meets_threshold = match rule {
        PumpRule::Delta => delta >= NORMAL_DELTA_MILLI_KPA,
        PumpRule::InletFloor => inlet >= NORMAL_INLET_MILLI_KPA,
    };
    let state = match (equipment.run, meets_threshold) {
        (false, _) => PumpState::Stopped,
        (true, true) => PumpState::Normal,
        (true, false) => PumpState::LowPressure,
    };
    let consistency = if equipment.alarm == (state == PumpState::LowPressure) {
        Consistency::Consistent
    } else {
        Consistency::Contradiction
    };
    Ok(PumpVerification {
        id: equipment.id.clone(),
        inlet_milli_kpa: inlet,
        outlet_milli_kpa: outlet,
        delta_milli_kpa: delta,
        state,
        consistency,
    })
}

pub fn verify_scene(scene: &Scene) -> Result<SceneVerification, OracleError> {
    verify_scene_with_rule(scene, PumpRule::Delta)
}

pub fn verify_scene_with_rule(
    scene: &Scene,
    rule: PumpRule,
) -> Result<SceneVerification, OracleError> {
    if scene.schema_version != SCHEMA_VERSION {
        return Err(OracleError::SchemaVersion(scene.schema_version.clone()));
    }
    if !(1..=2).contains(&scene.equipment.len()) {
        return Err(OracleError::InvalidScene("expected one or two pumps"));
    }
    if scene.seed > MAX_SAFE_INTEGER as u64 {
        return Err(OracleError::InvalidScene(
            "seed exceeds the safe integer range",
        ));
    }
    if !is_identifier(&scene.base_scene_id)
        || !is_identifier(&scene.layout_family)
        || !is_identifier(&scene.style_family)
    {
        return Err(OracleError::InvalidScene(
            "scene identity and layout/style must be valid identifiers",
        ));
    }
    if scene
        .equipment
        .iter()
        .any(|pump| !is_identifier(&pump.id) || !is_label(&pump.label))
    {
        return Err(OracleError::InvalidScene(
            "pump IDs and labels must meet the shared contract",
        ));
    }
    if let [first, second] = scene.equipment.as_slice() {
        if first.id == second.id || first.label == second.label {
            return Err(OracleError::InvalidScene(
                "pump IDs and labels must be unique",
            ));
        }
    }
    let equipment = scene
        .equipment
        .iter()
        .map(|pump| verify_equipment_with_rule(pump, rule))
        .collect::<Result<_, _>>()?;
    Ok(SceneVerification {
        base_scene_id: scene.base_scene_id.clone(),
        equipment,
    })
}
