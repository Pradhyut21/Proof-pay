use std::io::Write;
use std::process::{Command, Stdio};

use serde_json::{json, Value};

fn verify(rule: Option<&str>) -> Value {
    let scene = json!({
        "schema_version": "1.0.0",
        "base_scene_id": "test-scene",
        "seed": 0,
        "layout_family": "test",
        "style_family": "test",
        "equipment": [{
            "id": "P1",
            "label": "Pump 1",
            "inlet": {"value_milli": 1500, "unit": "bar"},
            "outlet": {"value_milli": 100000, "unit": "kPa"},
            "run": true,
            "alarm": false
        }]
    });
    let mut command = Command::new(env!("CARGO_BIN_EXE_pp"));
    command.args(["verify", "--scenes", "-"]);
    if let Some(rule) = rule {
        command.args(["--rule", rule]);
    }
    let mut child = command
        .stdin(Stdio::piped())
        .stdout(Stdio::piped())
        .stderr(Stdio::piped())
        .spawn()
        .unwrap();
    writeln!(child.stdin.take().unwrap(), "{scene}").unwrap();
    let output = child.wait_with_output().unwrap();
    assert!(
        output.status.success(),
        "{}",
        String::from_utf8_lossy(&output.stderr)
    );
    serde_json::from_slice(&output.stdout).unwrap()
}

#[test]
fn inlet_floor_is_opt_in_and_keeps_the_existing_output_schema() {
    let legacy = verify(None);
    assert_eq!(legacy, verify(Some("delta")));
    assert_eq!(legacy["equipment"][0]["state"], "LOW_PRESSURE");
    assert_eq!(legacy["equipment"][0]["consistency"], "CONTRADICTION");
    assert_eq!(
        verify(Some("inlet-floor")),
        json!({
            "base_scene_id": "test-scene",
            "equipment": [{
                "id": "P1",
                "inlet_milli_kpa": 150_000,
                "outlet_milli_kpa": 100_000,
                "delta_milli_kpa": -50_000,
                "state": "NORMAL",
                "consistency": "CONSISTENT"
            }]
        })
    );
}
