//! Pure rules for the menu-bar title and notifications. No Tauri types here,
//! so `cargo test` exercises them without a window system.

use serde_json::Value;

/// What the app needs from `/v1/app/summary` between two polls.
#[derive(Debug, Clone, PartialEq)]
pub struct Snapshot {
    pub today_microcents: i64,
    pub budget_state: String,
    pub used_percent: Option<f64>,
    pub daily_cents: Option<i64>,
    pub failures_avoided: i64,
}

#[derive(Debug, Clone, PartialEq)]
pub enum Alert {
    BudgetWarn { used_percent: f64, limit: String },
    BudgetOver { limit: String },
    Rescued { count: i64 },
}

pub fn money(microcents: i64) -> String {
    let cents = (microcents.max(0) + 5_000) / 10_000;
    let dollars = (cents / 100).to_string();
    let mut grouped = String::new();
    for (i, ch) in dollars.chars().enumerate() {
        if i > 0 && (dollars.len() - i) % 3 == 0 {
            grouped.push(',');
        }
        grouped.push(ch);
    }
    format!("${}.{:02}", grouped, cents % 100)
}

pub fn parse_summary(v: &Value) -> Option<Snapshot> {
    let today = v.get("today")?.get("spend_microcents")?.as_i64()?;
    let week = v.get("week")?;
    let budget = v.get("budget")?;
    Some(Snapshot {
        today_microcents: today,
        budget_state: budget.get("state")?.as_str()?.to_string(),
        used_percent: budget.get("used_percent").and_then(Value::as_f64),
        daily_cents: budget.get("daily_cents").and_then(Value::as_i64),
        failures_avoided: week.get("failures_avoided").and_then(Value::as_i64).unwrap_or(0),
    })
}

/// Parse `date +%z` output (`+0200`, `-0530`) into minutes east of UTC.
pub fn parse_utc_offset(s: &str) -> Option<i64> {
    let (sign, digits) = match s.chars().next()? {
        '+' => (1, &s[1..]),
        '-' => (-1, &s[1..]),
        _ => return None,
    };
    if digits.len() != 4 || !digits.chars().all(|c| c.is_ascii_digit()) {
        return None;
    }
    let h: i64 = digits[0..2].parse().ok()?;
    let m: i64 = digits[2..4].parse().ok()?;
    Some(sign * (h * 60 + m))
}

pub fn tray_title(s: &Snapshot) -> String {
    money(s.today_microcents)
}

fn rank(state: &str) -> u8 {
    match state {
        "warn" => 1,
        "over" => 2,
        _ => 0,
    }
}

pub fn alerts(prev: Option<&Snapshot>, cur: &Snapshot) -> Vec<Alert> {
    let Some(prev) = prev else {
        return Vec::new(); // never alert on launch for something already true
    };
    let mut out = Vec::new();
    let limit = || money(cur.daily_cents.unwrap_or(0) * 10_000);
    if rank(&cur.budget_state) > rank(&prev.budget_state) {
        match cur.budget_state.as_str() {
            "warn" => out.push(Alert::BudgetWarn {
                used_percent: cur.used_percent.unwrap_or(0.0),
                limit: limit(),
            }),
            "over" => out.push(Alert::BudgetOver { limit: limit() }),
            _ => {}
        }
    }
    if cur.failures_avoided > prev.failures_avoided {
        out.push(Alert::Rescued { count: cur.failures_avoided - prev.failures_avoided });
    }
    out
}

impl Alert {
    pub fn title(&self) -> String {
        match self {
            Alert::BudgetWarn { used_percent, limit } => {
                format!("{:.0}% of today's {} budget used", used_percent, limit)
            }
            Alert::BudgetOver { limit } => format!("Today's {} budget is used up", limit),
            Alert::Rescued { count } => format!(
                "{} {} rescued by fallback",
                count,
                if *count == 1 { "request" } else { "requests" }
            ),
        }
    }

    pub fn body(&self) -> String {
        match self {
            Alert::BudgetWarn { .. } => "Your coding agents keep working. Open Orca to see which agent is spending.".into(),
            Alert::BudgetOver { .. } => "Your agents keep working; Orca only alerts. Raise the budget or switch to auto-routing in Orca.".into(),
            Alert::Rescued { .. } => "A provider failed or rate-limited you, and Orca sent the request elsewhere.".into(),
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use serde_json::json;

    fn snap(today: i64, state: &str, pct: Option<f64>, daily: Option<i64>, rescued: i64) -> Snapshot {
        Snapshot {
            today_microcents: today,
            budget_state: state.into(),
            used_percent: pct,
            daily_cents: daily,
            failures_avoided: rescued,
        }
    }

    #[test]
    fn money_rounds_half_up_to_cents() {
        assert_eq!(money(0), "$0.00");
        assert_eq!(money(4_999), "$0.00");
        assert_eq!(money(5_000), "$0.01");
        assert_eq!(money(3_200_000), "$3.20");
        assert_eq!(money(123_456_789_000), "$123,456.79");
    }

    #[test]
    fn parses_the_engine_summary() {
        let v = json!({
            "today": {"spend_microcents": 3_200_000, "requests": 4},
            "week": {"spend_microcents": 9, "failures_avoided": 2},
            "budget": {"daily_cents": 2000, "used_percent": 16.0, "state": "ok"}
        });
        assert_eq!(parse_summary(&v), Some(snap(3_200_000, "ok", Some(16.0), Some(2000), 2)));
    }

    #[test]
    fn parses_a_summary_without_budget() {
        let v = json!({
            "today": {"spend_microcents": 0},
            "week": {"failures_avoided": 0},
            "budget": {"daily_cents": null, "used_percent": null, "state": "none"}
        });
        assert_eq!(parse_summary(&v), Some(snap(0, "none", None, None, 0)));
    }

    #[test]
    fn rejects_a_malformed_summary() {
        assert_eq!(parse_summary(&json!({"oops": 1})), None);
    }

    #[test]
    fn parses_date_utc_offsets_into_minutes_east() {
        assert_eq!(parse_utc_offset("+0200"), Some(120));
        assert_eq!(parse_utc_offset("-0530"), Some(-330));
        assert_eq!(parse_utc_offset("+0000"), Some(0));
        assert_eq!(parse_utc_offset("bogus"), None);
        assert_eq!(parse_utc_offset(""), None);
    }

    #[test]
    fn tray_title_is_todays_spend() {
        assert_eq!(tray_title(&snap(3_200_000, "ok", None, None, 0)), "$3.20");
    }

    #[test]
    fn first_poll_never_alerts() {
        assert!(alerts(None, &snap(9_000_000, "over", Some(450.0), Some(200), 5)).is_empty());
    }

    #[test]
    fn crossing_into_warn_alerts_once() {
        let a = snap(1_500_000, "ok", Some(75.0), Some(200), 0);
        let b = snap(1_700_000, "warn", Some(85.0), Some(200), 0);
        assert_eq!(alerts(Some(&a), &b), vec![Alert::BudgetWarn { used_percent: 85.0, limit: "$2.00".into() }]);
        assert!(alerts(Some(&b), &b).is_empty());
    }

    #[test]
    fn crossing_into_over_alerts_even_when_skipping_warn() {
        let a = snap(100, "ok", Some(1.0), Some(200), 0);
        let b = snap(2_500_000, "over", Some(125.0), Some(200), 0);
        assert_eq!(alerts(Some(&a), &b), vec![Alert::BudgetOver { limit: "$2.00".into() }]);
    }

    #[test]
    fn new_day_resets_without_alerting() {
        let late = snap(2_500_000, "over", Some(125.0), Some(200), 0);
        let morning = snap(0, "ok", Some(0.0), Some(200), 0);
        assert!(alerts(Some(&late), &morning).is_empty());
    }

    #[test]
    fn rescued_requests_alert_with_the_new_count() {
        let a = snap(0, "none", None, None, 3);
        let b = snap(0, "none", None, None, 7);
        assert_eq!(alerts(Some(&a), &b), vec![Alert::Rescued { count: 4 }]);
    }

    #[test]
    fn alert_copy_is_specific() {
        let w = Alert::BudgetWarn { used_percent: 85.0, limit: "$20.00".into() };
        assert_eq!(w.title(), "85% of today's $20.00 budget used");
        let o = Alert::BudgetOver { limit: "$20.00".into() };
        assert_eq!(o.title(), "Today's $20.00 budget is used up");
        let r = Alert::Rescued { count: 1 };
        assert_eq!(r.title(), "1 request rescued by fallback");
        assert_eq!(Alert::Rescued { count: 3 }.title(), "3 requests rescued by fallback");
        assert!(!o.body().is_empty());
    }
}
