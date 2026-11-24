use pp_scoring::score;
use serde_json::Value;

#[test]
fn scoring_goldens_match() {
    let raw = include_str!("../../../shared/golden/pump_rules.json");
    let g: Value = serde_json::from_str(raw).unwrap();
    for c in g["scoring"].as_array().unwrap() {
        let got = score(&c["answer"], &c["response"]);
        assert_eq!(got.as_str(), c["expect"].as_str().unwrap(), "{c}");
    }
}
