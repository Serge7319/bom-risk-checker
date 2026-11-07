/**
 * Node runner for BOM workflow stage + account-scoped analyze job contracts.
 * Invoked by tests/test_bom_workflow_guide_states.py
 */
import { pathToFileURL } from "node:url";
import path from "node:path";
import { fileURLToPath } from "node:url";

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "../..");
const webSrc = path.join(root, "apps/web/src/lib");

const baseCtx = () => ({
  hasFile: false,
  validating: false,
  validation: null,
  validationError: "",
  validationMatchesFile: false,
  analyzing: false,
  analyzeError: "",
  summary: null,
  analysisId: null,
  review: null,
  hasDecisionRecord: false,
  monitoringAvailable: false,
});

const validPreview = {
  ok: true,
  can_analyze: true,
  filename: "sample.csv",
  detected_columns: [],
  required_columns: ["mpn"],
  missing_required: [],
  row_count: 3,
  unique_part_count: 2,
  parsed_row_count: 2,
  errors: [],
  warnings: [],
};

function assert(cond, msg) {
  if (!cond) throw new Error(msg);
}

function waitMicrotasks() {
  return new Promise((resolve) => setTimeout(resolve, 0));
}

async function loadWorkflow() {
  return import(pathToFileURL(path.join(webSrc, "bomWorkflow.ts")).href);
}

async function loadJobs() {
  return import(pathToFileURL(path.join(webSrc, "bomAnalyzeJobs.ts")).href);
}

async function runWorkflowCases() {
  const { buildWorkflowGuide } = await loadWorkflow();
  const cases = [];

  {
    const g = buildWorkflowGuide(baseCtx());
    assert(g.currentStage === "Received", `initial current=${g.currentStage}`);
    assert(g.readyToAnalyze === false, "initial not ready");
    assert(g.primaryCta.action === "choose-file", "initial CTA");
    cases.push("initial");
  }

  {
    const g = buildWorkflowGuide({
      ...baseCtx(),
      hasFile: true,
      validating: true,
    });
    assert(g.currentStage === "Validating", `validating current=${g.currentStage}`);
    assert(g.stages.find((s) => s.id === "Analyzing").status !== "current", "analyzing not current while validating");
    assert(g.primaryCta.disabled === true, "validating CTA disabled");
    cases.push("validating");
  }

  {
    const g = buildWorkflowGuide({
      ...baseCtx(),
      hasFile: true,
      validation: validPreview,
      validationMatchesFile: true,
    });
    assert(g.readyToAnalyze === true, "ready flag");
    assert(g.currentStage === "Validating", `ready current should stay Validating, got ${g.currentStage}`);
    assert(g.stages.find((s) => s.id === "Validating").status === "complete", "validating complete when ready");
    assert(g.stages.find((s) => s.id === "Analyzing").status === "next", "analyzing is next when ready");
    assert(g.primaryCta.action === "analyze", "ready primary analyze");
    assert(!/start analysis after validation passes/i.test(g.announcement), "no misleading ready copy");
    assert(/ready to analyze/i.test(g.announcement), `announcement=${g.announcement}`);
    cases.push("ready");
  }

  {
    const g = buildWorkflowGuide({
      ...baseCtx(),
      hasFile: true,
      validation: validPreview,
      validationMatchesFile: true,
      analyzing: true,
    });
    assert(g.currentStage === "Analyzing", `analyzing current=${g.currentStage}`);
    assert(g.readyToAnalyze === false, "not ready while analyzing");
    assert(g.primaryCta.disabled === true, "analyzing CTA disabled");
    cases.push("analyzing");
  }

  {
    const g = buildWorkflowGuide({
      ...baseCtx(),
      hasFile: true,
      validation: validPreview,
      validationMatchesFile: true,
      summary: { analysis_id: "a1", total_parts: 2 },
      analysisId: "a1",
    });
    assert(g.currentStage === "Risks", `success current=${g.currentStage}`);
    assert(g.stages.find((s) => s.id === "Analyzing").status === "complete", "analyzing complete");
    assert(g.primaryCta.href?.includes("/reports/a1"), `cta href=${g.primaryCta.href}`);
    cases.push("success");
  }

  {
    const g = buildWorkflowGuide({
      ...baseCtx(),
      hasFile: true,
      validation: validPreview,
      validationMatchesFile: true,
      analyzeError: "boom",
    });
    assert(g.currentStage === "Analyzing", `error current=${g.currentStage}`);
    assert(g.stages.find((s) => s.id === "Analyzing").status === "error", "analyzing error status");
    assert(g.primaryCta.action === "retry-analyze", "retry CTA");
    cases.push("error");
  }

  {
    const g = buildWorkflowGuide({
      ...baseCtx(),
      hasFile: true,
      validation: validPreview,
      validationMatchesFile: false,
    });
    assert(g.readyToAnalyze === false, "stale validation not ready");
    assert(g.primaryCta.action !== "analyze", "stale cannot analyze");
    cases.push("stale-validation");
  }

  return cases;
}

async function runAccountIsolation() {
  const {
    startAnalyzeJobWithRunner,
    subscribeAnalyzeJob,
    getActiveAnalyzeJob,
    resetAnalyzeJobsForTests,
    clearFinishedAnalyzeJob,
  } = await loadJobs();

  resetAnalyzeJobsForTests();
  const userA = { user_id: "user-a", email: "a@cadivor.test", workspace_id: "ws-a" };
  const userB = { user_id: "user-b", email: "b@cadivor.test", workspace_id: "ws-b" };
  const file = { name: "sample.csv" };

  const pending = [];
  const runner = () =>
    new Promise((resolve, reject) => {
      pending.push({ resolve, reject });
    });

  const seenA = [];
  const seenB = [];
  const unsubA = subscribeAnalyzeJob((job) => seenA.push(job ? { ...job, result: job.result } : null), userA);
  const unsubB = subscribeAnalyzeJob((job) => seenB.push(job ? { ...job, result: job.result } : null), userB);

  startAnalyzeJobWithRunner(file, "token-a", { bomName: "A" }, userA, runner);
  assert(getActiveAnalyzeJob(userA)?.status === "running", "A running");
  assert(getActiveAnalyzeJob(userB) == null, "B must not see A's running job");

  startAnalyzeJobWithRunner(file, "token-b", { bomName: "B" }, userB, runner);
  assert(getActiveAnalyzeJob(userB)?.status === "running", "B running");
  assert(getActiveAnalyzeJob(userA)?.status === "running", "A still running after B starts");
  assert(pending.length === 2, `expected 2 pending analyzes, got ${pending.length}`);

  assert(seenA.some((j) => j && j.status === "running" && j.ownerKey === "user-a"), "A listener got A");
  assert(seenB.some((j) => j && j.status === "running" && j.ownerKey === "user-b"), "B listener got B");
  assert(!seenA.some((j) => j && j.ownerKey === "user-b"), "A never sees B");
  assert(!seenB.some((j) => j && j.ownerKey === "user-a"), "B never sees A");

  const resultA = {
    analysis_id: "analysis-a",
    total_parts: 2,
    health_score: 80,
    health_status: "ok",
    high_risk_count: 0,
    medium_risk_count: 0,
    low_risk_count: 2,
    mode: "synthetic-preview",
  };
  const resultB = { ...resultA, analysis_id: "analysis-b" };

  pending.shift().resolve(resultA);
  await waitMicrotasks();
  assert(getActiveAnalyzeJob(userA)?.status === "succeeded", "A succeeded");
  assert(getActiveAnalyzeJob(userA)?.result?.analysis_id === "analysis-a", "A keeps own result");
  assert(getActiveAnalyzeJob(userB)?.status === "running", "B still running after A finishes");
  assert(!seenB.some((j) => j && j.result && j.result.analysis_id === "analysis-a"), "B never received A's result");

  pending.shift().resolve(resultB);
  await waitMicrotasks();
  assert(getActiveAnalyzeJob(userB)?.result?.analysis_id === "analysis-b", "B keeps own result");
  assert(!seenA.some((j) => j && j.result && j.result.analysis_id === "analysis-b"), "A never received B's result");

  clearFinishedAnalyzeJob(userA);
  assert(getActiveAnalyzeJob(userA) == null, "A cleared");
  assert(getActiveAnalyzeJob(userB)?.status === "succeeded", "B still present after A clear");
  clearFinishedAnalyzeJob(userB);

  unsubA();
  unsubB();
  resetAnalyzeJobsForTests();
  return ["account-switch-in-flight"];
}

const suite = process.argv[2] || "all";
const results = { ok: true, cases: [] };
try {
  if (suite === "workflow" || suite === "all") {
    results.cases.push(...(await runWorkflowCases()));
  }
  if (suite === "jobs" || suite === "all") {
    results.cases.push(...(await runAccountIsolation()));
  }
  console.log(JSON.stringify(results));
} catch (err) {
  console.log(JSON.stringify({ ok: false, error: String(err?.stack || err), cases: results.cases }));
  process.exitCode = 1;
}
