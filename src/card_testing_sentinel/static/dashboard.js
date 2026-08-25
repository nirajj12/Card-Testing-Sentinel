let timeline = [];
let step = 0;
let timer = null;
const $ = (id) => document.getElementById(id);
const pct = (value) => `${(100 * value).toFixed(2)}%`;
const reasons = {
  velocity_card_diversity: "rapid authorization velocity across multiple cards",
  rapid_card_switching: "rapid card switching",
  repeated_declines: "repeated decline behavior",
  near_minimum_probing: "amounts repeatedly near the configured minimum",
  continued_after_approval: "attempts continued after an approval",
};

async function getDevices(params = {}) {
  const query = new URLSearchParams({ page_size: "50", ...params });
  return fetch(`/api/v1/devices?${query}`).then((response) => response.json());
}

async function setCatalogue(params = {}) {
  const devices = await getDevices(params);
  $("device").innerHTML = devices.items.map((device) =>
    `<option value="${device.device_id}">${device.population} · ${device.attack_subtype || device.scenario_exposures} · ${device.device_id}</option>`
  ).join("");
}

async function addQuickExample(label, params) {
  const devices = await getDevices(params);
  if (!devices.items.length) return;
  const button = document.createElement("button");
  button.textContent = label;
  button.onclick = () => load(devices.items[0].device_id);
  $("quick").appendChild(button);
}

async function init() {
  const [ready, metrics] = await Promise.all([
    fetch("/health/ready").then((response) => response.json()),
    fetch("/api/v1/metrics").then((response) => response.json()),
  ]);
  $("ready").textContent = `● ${ready.status}`;
  const row = metrics.static_champion_metrics;
  const champion = metrics.sequential_methods.rules_only.metrics;
  const attacker = champion.attacker_block_coverage;
  const legitimate = champion.legitimate_overall.ever_blocked;
  const cards = [
    ["HGB PR-AUC (authorization rows)", row.average_precision.toFixed(4)],
    ["HGB F1 (authorization rows)", row.f1.toFixed(4)],
    ["Attacker devices blocked", `${attacker.numerator_devices}/${attacker.denominator_devices} · ${pct(attacker.rate)}`],
    ["Legitimate devices blocked", `${legitimate.numerator_devices}/${legitimate.denominator_devices} · ${pct(legitimate.rate)}`],
    ["Median attempts through detection", champion.attempts_processed_through_detection.median],
    ["Never-detected attacker devices", `${champion.never_detected_attacker_devices}/${champion.total_attacker_devices} · ${pct(champion.never_detected_rate)}`],
  ];
  $("metrics").innerHTML = cards.map(([label, value]) => `<div class="card">${label}<strong>${value}</strong></div>`).join("");
  const flash = metrics.sequential_methods.rules_only.budgets.flash_sale_block;
  const patient = champion.attacker_subtypes.patient;
  const evasive = champion.attacker_subtypes.evasive;
  $("limitations").innerHTML = `<p><b>Flash-sale target miss:</b> ${flash.numerator_devices}/${flash.denominator_devices} blocked; only ${flash.maximum_allowed_devices} allowed.</p><p><b>Patient attackers missed:</b> ${patient.never_detected_devices}/${patient.detected.denominator_devices}. <b>Evasive attackers missed:</b> ${evasive.never_detected_devices}/${evasive.detected.denominator_devices}.</p>`;
  $("detection").innerHTML = Object.entries(champion.detected_within_attempt).sort((a, b) => Number(a[0]) - Number(b[0])).map(([k, value]) => `<div class="bar"><span>Within ${k}</span><div class="track"><div class="fill" style="width:${100 * value.rate}%"></div></div><b>${value.numerator_devices}/${value.denominator_devices}</b></div>`).join("");
  $("comparison").innerHTML = `<table><tr><th>Method</th><th>Review-or-higher</th><th>Blocked attackers</th><th>Blocked legitimate</th><th>Role</th></tr>${Object.entries(metrics.sequential_methods).map(([name, value]) => { const m = value.metrics; return `<tr><td>${name}</td><td>${m.attacker_review_or_higher_coverage.numerator_devices}/${m.attacker_review_or_higher_coverage.denominator_devices}</td><td>${m.attacker_block_coverage.numerator_devices}/${m.attacker_block_coverage.denominator_devices}</td><td>${m.legitimate_overall.ever_blocked.numerator_devices}/${m.legitimate_overall.ever_blocked.denominator_devices}</td><td>${name === "rules_only" ? "Selected champion" : "Comparison only"}</td></tr>`; }).join("")}</table>`;
  await setCatalogue();
  await Promise.all([
    addQuickExample("Detected burst", { population: "attack", attack_subtype: "burst", detected: "true" }),
    addQuickExample("Detected evasive", { population: "attack", attack_subtype: "evasive", detected: "true" }),
    addQuickExample("Never-detected patient", { population: "attack", attack_subtype: "patient", detected: "false" }),
    addQuickExample("Blocked hard retry", { population: "flash_sale", scenario_exposure: "flash_hard_retry", detected: "true" }),
    addQuickExample("Allowed normal", { population: "normal", scenario_exposure: "normal_standard", detected: "false" }),
  ]);
}

async function load(deviceId = $("device").value) {
  clearInterval(timer);
  const data = await fetch(`/api/v1/devices/${deviceId}/timeline`).then((response) => response.json());
  timeline = data.events;
  step = 0;
  $("summary").textContent = `Detected: ${data.summary.ever_blocked} · first block: ${data.summary.first_block_position ?? "never"} · attempts through detection: ${data.summary.attempts_processed_through_detection ?? "never"} · remaining recorded: ${data.summary.remaining_recorded_attempts_after_detection ?? 0}. ${data.disclaimer}`;
  show();
}

function show() {
  if (!timeline.length) return;
  const event = timeline[step];
  const explanation = event.rule_reason_codes.map((code) => reasons[code] || code).join("; ") || "no rule signal";
  const marker = event.is_first_block ? '<strong class="marker">First block-triggering authorization</strong><br>' : "";
  const prevented = event.potentially_prevented ? '<p class="block">Replay-estimated potentially preventable (offline upper bound)</p>' : "";
  $("event").innerHTML = `${marker}<b>Attempt ${event.authorization_position}/${timeline.length}</b> · ${event.display_card} · +${Number(event.relative_seconds).toFixed(1)}s<br>Advisory HGB risk ${Number(event.advisory_model_risk_probability).toFixed(4)} · Rule score ${event.rule_score}<br><span class="${event.selected_action.includes("block") ? "block" : "allow"}">Rules-only action: ${event.selected_action}</span> · ${explanation}<br>Comparison only — ML: ${event.comparison_actions.ml_only}; combined: ${event.comparison_actions.combined}${prevented}`;
}

$("filter").onclick = () => setCatalogue({ population: $("population").value, attack_subtype: $("subtype").value, detected: $("detected").value });
$("load").onclick = () => load();
$("play").onclick = () => { clearInterval(timer); timer = setInterval(() => { step = Math.min(step + 1, timeline.length - 1); show(); if (step === timeline.length - 1) clearInterval(timer); }, Number($("speed").value)); };
$("pause").onclick = () => clearInterval(timer);
$("next").onclick = () => { step = Math.min(step + 1, timeline.length - 1); show(); };
$("prev").onclick = () => { step = Math.max(step - 1, 0); show(); };
$("reset").onclick = () => { clearInterval(timer); step = 0; show(); };
init();
