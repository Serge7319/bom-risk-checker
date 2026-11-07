/**
 * Node runner for BOM workflow stage + user/workspace-scoped analyze job contracts.
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

async function loadFileIdentity() {
  return import(pathToFileURL(path.join(webSrc, "bomFileIdentity.ts")).href);
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
      summary: {
        analysis_id: "a1",
        total_parts: 2,
        health_score: 80,
        health_status: "ok",
        high_risk_count: 0,
        medium_risk_count: 0,
        low_risk_count: 2,
        mode: "synthetic-preview",
      },
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
    identityKey,
    parseAnalyzeSummary,
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

  assert(seenA.some((j) => j && j.status === "running" && j.ownerKey === identityKey(userA)), "A listener got A");
  assert(seenB.some((j) => j && j.status === "running" && j.ownerKey === identityKey(userB)), "B listener got B");
  assert(!seenA.some((j) => j && j.ownerKey === identityKey(userB)), "A never sees B");
  assert(!seenB.some((j) => j && j.ownerKey === identityKey(userA)), "B never sees A");

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

  // Incomplete payloads must not become succeeded summaries.
  resetAnalyzeJobsForTests();
  const incompletePending = [];
  const incompleteRunner = () =>
    new Promise((resolve) => incompletePending.push(resolve));
  startAnalyzeJobWithRunner(file, "token-a", { bomName: "A" }, userA, incompleteRunner);
  incompletePending.shift()({ analysis_id: "partial-only" });
  await waitMicrotasks();
  assert(getActiveAnalyzeJob(userA)?.status === "failed", "incomplete summary fails closed");
  assert(parseAnalyzeSummary({ analysis_id: "x" }) == null, "parseAnalyzeSummary rejects incomplete");

  clearFinishedAnalyzeJob(userA);
  clearFinishedAnalyzeJob(userB);

  unsubA();
  unsubB();
  resetAnalyzeJobsForTests();
  return ["account-switch-in-flight"];
}

async function runWorkspaceIsolation() {
  const {
    startAnalyzeJobWithRunner,
    subscribeAnalyzeJob,
    getActiveAnalyzeJob,
    resetAnalyzeJobsForTests,
    clearFinishedAnalyzeJob,
    identityKey,
  } = await loadJobs();
  const { draftMetaStorageKey, draftFileRecordId } = await loadFileIdentity();

  resetAnalyzeJobsForTests();
  const wsA = { user_id: "user-same", email: "same@cadivor.test", workspace_id: "ws-a" };
  const wsB = { user_id: "user-same", email: "same@cadivor.test", workspace_id: "ws-b" };
  assert(identityKey(wsA) !== identityKey(wsB), "workspace identity keys differ");
  assert(draftMetaStorageKey(wsA) !== draftMetaStorageKey(wsB), "draft meta keys differ by workspace");
  assert(draftFileRecordId(wsA) !== draftFileRecordId(wsB), "draft file ids differ by workspace");

  // localStorage-backed draft meta isolation (jsdom-free stub).
  const store = new Map();
  globalThis.window = {
    localStorage: {
      getItem: (k) => (store.has(k) ? store.get(k) : null),
      setItem: (k, v) => store.set(k, String(v)),
      removeItem: (k) => store.delete(k),
    },
  };

  const draftA = {
    projectName: "Workspace A project",
    fileKey: "sha256:aaa",
    analysisId: "analysis-ws-a",
  };
  window.localStorage.setItem(draftMetaStorageKey(wsA), JSON.stringify(draftA));
  const rawA = JSON.parse(window.localStorage.getItem(draftMetaStorageKey(wsA)));
  const rawB = window.localStorage.getItem(draftMetaStorageKey(wsB));
  assert(rawA.projectName === "Workspace A project", "wsA reads own draft");
  assert(rawB == null, "wsB must not restore wsA draft meta");

  const pending = [];
  const runner = () => new Promise((resolve) => pending.push(resolve));
  const seenB = [];
  const unsubB = subscribeAnalyzeJob((job) => seenB.push(job), wsB);
  startAnalyzeJobWithRunner({ name: "a.csv" }, "tok", { bomName: "A" }, wsA, runner);
  assert(getActiveAnalyzeJob(wsA)?.status === "running", "wsA job running");
  assert(getActiveAnalyzeJob(wsB) == null, "same user in wsB must not see wsA job");
  assert(!seenB.some((j) => j && j.status === "running"), "wsB listener never observes wsA job");

  pending.shift()({
    analysis_id: "analysis-ws-a",
    total_parts: 1,
    health_score: 70,
    health_status: "ok",
    high_risk_count: 0,
    medium_risk_count: 0,
    low_risk_count: 1,
    mode: "synthetic-preview",
  });
  await waitMicrotasks();
  assert(getActiveAnalyzeJob(wsA)?.result?.analysis_id === "analysis-ws-a", "wsA keeps result");
  assert(getActiveAnalyzeJob(wsB) == null, "wsB still has no job after wsA succeeds");
  assert(!seenB.some((j) => j && j.result), "wsB never receives wsA result");

  clearFinishedAnalyzeJob(wsA);
  unsubB();
  resetAnalyzeJobsForTests();
  delete globalThis.window;
  return ["workspace-switch-same-user"];
}

async function runFileIdentityCases() {
  const { fileIdentityKey } = await loadFileIdentity();
  const stamp = 1_700_000_000_000;
  const left = new File([Buffer.from("MPN,Qty\nAAA,1\n")], "same.csv", {
    type: "text/csv",
    lastModified: stamp,
  });
  const right = new File([Buffer.from("MPN,Qty\nBBB,1\n")], "same.csv", {
    type: "text/csv",
    lastModified: stamp,
  });
  assert(left.size === right.size, "fixture sizes must match for regression");
  assert(left.name === right.name && left.lastModified === right.lastModified, "meta matches");
  const keyLeft = await fileIdentityKey(left);
  const keyRight = await fileIdentityKey(right);
  assert(keyLeft !== keyRight, `content keys must differ: ${keyLeft} vs ${keyRight}`);
  assert(keyLeft.startsWith("sha256:"), `left key=${keyLeft}`);
  assert(keyRight.startsWith("sha256:"), `right key=${keyRight}`);
  // Same bytes → same key
  const leftAgain = await fileIdentityKey(
    new File([Buffer.from("MPN,Qty\nAAA,1\n")], "same.csv", { type: "text/csv", lastModified: stamp }),
  );
  assert(leftAgain === keyLeft, "identical bytes keep the same identity");
  return ["content-identity-same-meta-different-bytes"];
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
  if (suite === "workspace" || suite === "all") {
    results.cases.push(...(await runWorkspaceIsolation()));
  }
  if (suite === "identity" || suite === "all") {
    results.cases.push(...(await runFileIdentityCases()));
  }
  console.log(JSON.stringify(results));
} catch (err) {
  console.log(JSON.stringify({ ok: false, error: String(err?.stack || err), cases: results.cases }));
  process.exitCode = 1;
}
