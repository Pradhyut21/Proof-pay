use pp_oracle::{convert_milli, pump_state, to_milli_kpa};
use serde_json::Value;

fn golden() -> Value {
    let raw = include_str!("../../../shared/golden/pump_rules.json");
    serde_json::from_str(raw).expect("golden parses")
}

#[test]
fn pump_rule_goldens_match() {
    let g = golden();
    let cases = g["pump_rules"].as_array().unwrap();
    assert!(cases.len() >= 20);
    for c in cases {
        let id = c["id"].as_str().unwrap();
        let unit = |k: &str| {
            let v = &c[k];
            to_milli_kpa(
                v["value_milli"].as_i64().unwrap(),
                v["unit"].as_str().unwrap(),
            )
            .unwrap()
        };
        let (i, o) = (unit("inlet"), unit("outlet"));
        assert_eq!(i, c["inlet_mkpa"].as_i64().unwrap(), "{id} inlet");
        assert_eq!(o, c["outlet_mkpa"].as_i64().unwrap(), "{id} outlet");
        assert_eq!(o - i, c["delta_mkpa"].as_i64().unwrap(), "{id} delta");
        let s = pump_state(c["run"].as_bool().unwrap(), i, o);
        assert_eq!(s.as_str(), c["state"].as_str().unwrap(), "{id} state");
    }
}

#[test]
fn unit_conversion_goldens_match() {
    for c in golden()["units"].as_array().unwrap() {
        let got = convert_milli(
            c["value_milli"].as_i64().unwrap(),
            c["from"].as_str().unwrap(),
            c["to"].as_str().unwrap(),
        )
        .unwrap();
        assert_eq!(got, c["expect"].as_i64().unwrap(), "{c}");
    }
}
