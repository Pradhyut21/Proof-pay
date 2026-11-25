use panelproof_oracle::{
    convert_to_milli_kpa, verify_equipment, verify_equipment_with_rule, Consistency, Equipment,
    Pressure, PressureUnit, PumpRule, PumpState, MAX_SAFE_INTEGER,
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

#[test]
fn inlet_floor_checks_mixed_units_alarm_and_the_inclusive_boundary() {
    let mut pump = Equipment {
        id: "P1".into(),
        label: "Pump 1".into(),
        inlet: Pressure {
            value_milli: 1_500,
            unit: PressureUnit::Bar,
        },
        outlet: Pressure {
            value_milli: 100_000,
            unit: PressureUnit::Kpa,
        },
        run: true,
        alarm: false,
    };
    let exact = verify_equipment_with_rule(&pump, PumpRule::InletFloor).unwrap();
    assert_eq!(exact.inlet_milli_kpa, 150_000);
    assert_eq!(exact.delta_milli_kpa, -50_000);
    assert_eq!(exact.state, PumpState::Normal);
    assert_eq!(exact.consistency, Consistency::Consistent);
    assert_eq!(
        verify_equipment(&pump).unwrap().state,
        PumpState::LowPressure
    );

    pump.inlet = Pressure {
        value_milli: 149_999,
        unit: PressureUnit::Kpa,
    };
    pump.outlet.value_milli = 500_000;
    let below = verify_equipment_with_rule(&pump, PumpRule::InletFloor).unwrap();
    assert_eq!(below.state, PumpState::LowPressure);
    assert_eq!(below.consistency, Consistency::Contradiction);
    assert_eq!(verify_equipment(&pump).unwrap().state, PumpState::Normal);

    pump.alarm = true;
    let alarm = verify_equipment_with_rule(&pump, PumpRule::InletFloor).unwrap();
    assert_eq!(alarm.consistency, Consistency::Consistent);

    pump.run = false;
    let stopped = verify_equipment_with_rule(&pump, PumpRule::InletFloor).unwrap();
    assert_eq!(stopped.state, PumpState::Stopped);
    assert_eq!(stopped.consistency, Consistency::Contradiction);
}
