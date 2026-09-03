import { publicEvidence } from "../data/publicEvidence";

type Scenario = {
  name: string;
  reviewPlusPct: number;
  blockPct: number;
};

function GroupedBarChart({
  title,
  description,
  rows,
  kind,
}: {
  title: string;
  description: string;
  rows: readonly Scenario[];
  kind: "attack" | "friction";
}) {
  const summary = rows
    .map(
      (row) =>
        `${row.name}: REVIEW or BLOCK ${row.reviewPlusPct}%, BLOCK ${row.blockPct}%`,
    )
    .join(". ");

  return (
    <figure className={`native-chart grouped-bars ${kind}`}>
      <figcaption>
        <span>{kind === "attack" ? "Attack profiles" : "Genuine profiles"}</span>
        <h3>{title}</h3>
        <p>{description}</p>
      </figcaption>
      <div className="chart-key" aria-label="Chart legend">
        <span><i className="review-key" />REVIEW+</span>
        <span><i className="block-key" />BLOCK</span>
      </div>
      <div className="vertical-chart" role="img" aria-label={summary}>
        <div className="chart-y-axis" aria-hidden="true">
          {[100, 75, 50, 25, 0].map((tick) => <span key={tick}>{tick}%</span>)}
        </div>
        <div className="chart-groups">
          {rows.map((row) => (
            <div className="chart-group" key={row.name}>
              <div className="bar-pair">
                <div
                  className="chart-bar review-bar"
                  style={{ height: `${row.reviewPlusPct}%` }}
                >
                  <strong>{row.reviewPlusPct}%</strong>
                </div>
                <div
                  className="chart-bar block-bar"
                  style={{ height: `${row.blockPct}%` }}
                >
                  <strong>{row.blockPct}%</strong>
                </div>
              </div>
              <span>{row.name}</span>
            </div>
          ))}
        </div>
      </div>
      <p className="sr-only">{summary}</p>
    </figure>
  );
}

function DetectionDelayChart() {
  const rows = publicEvidence.detectionDelay;
  const x = (attempt: number) => 58 + ((attempt - 1) / 4) * 500;
  const y = (value: number) => 250 - (value / 100) * 205;
  const points = rows.map((row) => `${x(row.attempt)},${y(row.surfacedPct)}`).join(" ");
  const summary = rows
    .map((row) => `Attempt ${row.attempt}: ${row.surfacedPct}% surfaced`)
    .join(". ");

  return (
    <figure className="native-chart detection-chart">
      <figcaption>
        <span>Detection delay</span>
        <h3>Behavior becomes visible over repeated attempts</h3>
        <p>Early attempts contain little behavioral history. By the third attempt, repeated activity provides much stronger evidence.</p>
      </figcaption>
      <svg viewBox="0 0 620 315" role="img" aria-labelledby="delay-title delay-desc">
        <title id="delay-title">Cumulative attack profiles surfaced by attempt</title>
        <desc id="delay-desc">{summary}. No attempt 4 value is available or inferred.</desc>
        <g className="delay-grid" aria-hidden="true">
          {[50, 100, 150, 200, 250].map((lineY) => (
            <line key={lineY} x1="58" x2="570" y1={lineY} y2={lineY} />
          ))}
        </g>
        <rect className="early-zone" x="58" y="36" width="150" height="214" rx="12" />
        <text className="early-label" x="74" y="72">Limited history</text>
        <polyline className="delay-line" points={points} />
        <line className="attempt-three-guide" x1={x(3)} x2={x(3)} y1="36" y2="250" />
        {rows.map((row) => (
          <g key={row.attempt} className={row.attempt === 3 ? "jump-point" : ""}>
            <circle cx={x(row.attempt)} cy={y(row.surfacedPct)} r={row.attempt === 3 ? 8 : 6} />
            <text className="point-value" x={x(row.attempt)} y={y(row.surfacedPct) - 14} textAnchor="middle">
              {row.surfacedPct}%
            </text>
            <text className="attempt-label" x={x(row.attempt)} y="280" textAnchor="middle">
              Attempt {row.attempt}
            </text>
          </g>
        ))}
        <text className="jump-label" x={x(3) + 16} y="112">Sharp rise by attempt 3</text>
      </svg>
      <p className="chart-note">Only measured attempts are shown. Attempt 4 is not inferred.</p>
    </figure>
  );
}

export function EvaluationCharts() {
  return (
    <>
      <section className="results-chart-section page-width">
        <GroupedBarChart
          kind="attack"
          title="Attack coverage across stress scenarios"
          description="REVIEW+ means the profile reached REVIEW or BLOCK. BLOCK is shown separately."
          rows={publicEvidence.attackScenarios}
        />
      </section>
      <section className="results-chart-section delay-section page-width">
        <DetectionDelayChart />
      </section>
      <section className="results-chart-section page-width">
        <GroupedBarChart
          kind="friction"
          title="Where customer friction concentrates"
          description="Ordinary retry-heavy checkout traffic remains the largest source of unnecessary intervention."
          rows={publicEvidence.frictionScenarios}
        />
      </section>
    </>
  );
}
