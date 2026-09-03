export const ACTIVE_FEATURE_COUNT = 44;

const attackProfilesInterrupted = 1205;
const allProfilesInterrupted = 1982;

export const publicEvidence = {
  evaluation: {
    totalProfiles: 5000,
    attackProfiles: 1250,
    legitimateProfiles: 3750,
    syntheticMerchants: 16,
    attackRecallPct: 96.4,
    interventionPrecisionPct:
      (attackProfilesInterrupted / allProfilesInterrupted) * 100,
    legitimateInterventionPct: 20.72,
    legitimateBlockPct: 0.16,
    attackProfilesInterrupted,
    allProfilesInterrupted,
  },
  attackScenarios: [
    { name: "Stealth low-amount attack", reviewPlusPct: 100, blockPct: 100 },
    { name: "Hybrid credential probe", reviewPlusPct: 100, blockPct: 60.8 },
    { name: "Mixed-card probe", reviewPlusPct: 94, blockPct: 44.93 },
  ],
  detectionDelay: [
    { attempt: 1, surfacedPct: 23.2 },
    { attempt: 2, surfacedPct: 25.2 },
    { attempt: 3, surfacedPct: 92.16 },
    { attempt: 5, surfacedPct: 96.4 },
  ],
  frictionScenarios: [
    { name: "Charity spike", reviewPlusPct: 0, blockPct: 0 },
    { name: "B2B corporate-card traffic", reviewPlusPct: 7.2, blockPct: 0.8 },
    { name: "Ordinary checkout", reviewPlusPct: 25.3, blockPct: 0.13 },
  ],
  quality: {
    prAuc: 0.6469762178054731,
    rocAuc: 0.7261889167036668,
    brier: 0.15603701503584233,
    ece: 0.14067900697104643,
  },
  runtime: {
    p50Ms: 33.830896,
    p95Ms: 110.732069,
    requests: 500,
    errors: 0,
  },
  economics: [
    { name: "Quiet day", netValueInr: -708697.6 },
    { name: "Active attack campaign", netValueInr: 2971648 },
    { name: "High-value merchant", netValueInr: 2535480 },
  ],
} as const;

export const formatPercent = (value: number, digits = 1) =>
  `${value.toFixed(digits)}%`;
