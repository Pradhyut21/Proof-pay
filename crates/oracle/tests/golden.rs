use panelproof_oracle::{
    convert_to_milli_kpa, verify_equipment, Consistency, Equipment, Pressure, PressureUnit,
    PumpState, MAX_SAFE_INTEGER,
};
use serde::Deserialize;

#[derive(Deserialize)]
struct Golden {
    id: String,
    inlet: Pressure,
    outlet: Pressure,
    run: bool,
    alarm: bool,
    expected_state: PumpState,
    expected_consistency: Consistency,
}

#[test]
fn all_shared_rule_fixtures_agree() {
    let fixtures: Vec<Golden> =
        serde_json::from_str(include_str!("../../../shared/golden/pump_rules.json")).unwrap();
    assert!(fixtures.len() >= 20);
    for fixture in fixtures {
        let verified = verify_equipment(&Equipment {
            label: fixture.id.clone(),
            id: fixture.id.clone(),
            inlet: fixture.inlet,
            outlet: fixture.outlet,
            run: fixture.run,
            alarm: fixture.alarm,
        })
        .unwrap();
        assert_eq!(verified.state, fixture.expected_state, "{}", fixture.id);
        assert_eq!(
            verified.consistency, fixture.expected_consistency,
            "{}",
            fixture.id
        );
    }
}

#[test]
fn fixed_point_pressure_handles_signs_and_rejects_unsafe_input() {
    for (value_milli, expected) in [(1, 7), (-1, -7), (1_000, 6_895), (-1_000, -6_895)] {
        let pressure = Pressure {
            value_milli,
            unit: PressureUnit::Psi,
        };
        assert_eq!(convert_to_milli_kpa(pressure).unwrap(), expected);
    }
    assert!(convert_to_milli_kpa(Pressure {
        value_milli: MAX_SAFE_INTEGER + 1,
        unit: PressureUnit::Bar,
    })
    .is_err());
}
