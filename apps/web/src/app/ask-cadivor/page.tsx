"use client";

import Link from "next/link";
import { FormEvent, KeyboardEvent, Suspense, useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useRouter, useSearchParams } from "next/navigation";
import { formatCadivorAnswer } from "@/components/AskCadivorPanel";
import { EmptyState } from "@/components/EmptyState";
import { EvidenceNotice, LoadingCard } from "@/components/GapBanner";
import { Icon } from "@/components/Icons";
import { PageHeader, PrimaryLink, SecondaryLink } from "@/components/PageHeader";
import { Shell } from "@/components/Shell";
import {
  askCadivor,
  beginUsageOverageCheckout,
  fetchBillingStatus,
  fetchPlanUsage,
  fetchReport,
  listReports,
  type Report,
} from "@/lib/api";
import { cleanUserText, userFacingLabel } from "@/lib/display";
import { PAGE_META } from "@/lib/routes";
import { useRequireSession } from "@/lib/session";
import styles from "./askCadivor.module.css";

type AskMessage = {
  id: string;
  role: "user" | "assistant";
  content: string;
  createdAt: string;
  grounded?: boolean;
  gap?: string;
};

type AskConversation = {
  id: string;
  analysisId: string;
  title: string;
  createdAt: string;
  updatedAt: string;
  messages: AskMessage[];
};

type ThreadSnapshot = {
  key: string;
  loaded: boolean;
  threads: AskConversation[];
};

type EvidenceTab = "evidence" | "bom";

function reportId(report: Record<string, unknown>): string {
  return String(report.analysis_id || report.id || "").trim();
}

function reportName(report: Record<string, unknown> | null | undefined): string {
  return userFacingLabel(
    report?.bom_name || report?.filename || report?.project_name,
    "Saved BOM",
  );
}

function reportOptionLabel(report: Record<string, unknown>): string {
  const details = [
    report.project_name ? userFacingLabel(report.project_name, "Project") : "",
    report.revision ? "Rev " + String(report.revision) : "",
    report.created_at
      ? new Date(String(report.created_at)).toLocaleDateString()
      : "",
  ].filter(Boolean);
  return [reportName(report), ...details].join(" · ");
}

function fieldText(row: Record<string, unknown>, ...keys: string[]): string {
  for (const key of keys) {
    const value = row[key];
    if (Array.isArray(value)) {
      const items = value.map((item) => cleanUserText(item)).filter(Boolean);
      if (items.length) return items.join(" · ");
    } else if (value !== undefined && value !== null && String(value).trim()) {
      return cleanUserText(value).trim();
    }
  }
  return "";
}

function riskLabel(row: Record<string, unknown>): string {
  return fieldText(row, "Risk Level", "risk_level", "risk_status") || "Not assessed";
}

function riskTone(value: string): "high" | "medium" | "low" | "unknown" | "neutral" {
  const normalized = value.toLowerCase();
  if (/critical|high|blocker/.test(normalized)) return "high";
  if (/medium|moderate/.test(normalized)) return "medium";
  if (/low|clear|within/.test(normalized)) return "low";
  if (/unknown|unverified|not assessed|needs review|insufficient/.test(normalized)) {
    return "unknown";
  }
  return "neutral";
}

function riskRank(value: string): number {
  const tone = riskTone(value);
  if (tone === "high") return 0;
  if (tone === "medium") return 1;
  if (tone === "unknown") return 2;
  if (tone === "low") return 3;
  return 4;
}

function dateLabel(value: string): string {
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return "Date not recorded";
  const now = new Date();
  if (date.toDateString() === now.toDateString()) {
    return "Today · " + date.toLocaleTimeString([], { hour: "numeric", minute: "2-digit" });
  }
  const yesterday = new Date(now);
  yesterday.setDate(now.getDate() - 1);
  if (date.toDateString() === yesterday.toDateString()) return "Yesterday";
  return date.toLocaleDateString();
}

function makeId(): string {
  if (typeof crypto !== "undefined" && typeof crypto.randomUUID === "function") {
    return crypto.randomUUID();
  }
  return "ask-" + Date.now() + "-" + Math.random().toString(36).slice(2, 9);
}

function userFacingAskGap(value: unknown): string {
  const text = cleanUserText(value).trim();
  if (!text) return "";
  if (/admin requests do not consume plan credits/i.test(text)) return "";
  if (/OpenAI response used one monthly plan credit/i.test(text)) {
    const remaining = text.match(/(\d+)\s+remain/i)?.[1];
    return remaining
      ? `This answer used one monthly Cadivor AI credit; ${remaining} remain this month.`
      : "This answer used one monthly Cadivor AI credit.";
  }
  if (/OpenAI was not active/i.test(text)) {
    return "The AI response service was unavailable; Cadivor used its saved report evidence and built-in review rules.";
  }
  return text.replace(/OpenAI/gi, "AI");
}

function readStoredThreads(key: string): AskConversation[] {
  try {
    const raw = window.localStorage.getItem(key);
    const parsed = raw ? JSON.parse(raw) : [];
    if (!Array.isArray(parsed)) return [];
    return parsed
      .filter((item): item is AskConversation =>
        Boolean(
          item &&
            typeof item.id === "string" &&
            typeof item.analysisId === "string" &&
            typeof item.title === "string" &&
            Array.isArray(item.messages),
        ),
      )
      .map((item) => ({
        ...item,
        messages: item.messages
          .filter(
            (message: AskMessage) =>
              message &&
              typeof message.id === "string" &&
              (message.role === "user" || message.role === "assistant") &&
              typeof message.content === "string",
          )
          .map((message: AskMessage) => ({
            id: message.id,
            role: message.role,
            content: message.content,
            createdAt: message.createdAt,
            grounded: message.grounded,
            gap: userFacingAskGap(message.gap),
          })),
      }))
      .sort((a, b) => Date.parse(b.updatedAt) - Date.parse(a.updatedAt))
      .slice(0, 25);
  } catch {
    return [];
  }
}

function conversationTitle(question: string): string {
  const singleLine = question.replace(/\s+/g, " ").trim();
  return singleLine.length > 64 ? singleLine.slice(0, 61) + "…" : singleLine;
}

function objectValue(value: unknown): Record<string, unknown> {
  return value && typeof value === "object" && !Array.isArray(value)
    ? value as Record<string, unknown>
    : {};
}

function moneyLabel(minorAmount: unknown): string {
  const amount = Number(minorAmount);
  if (!Number.isFinite(amount) || amount < 0) return "Price unavailable";
  return new Intl.NumberFormat(undefined, { style: "currency", currency: "USD" }).format(amount / 100);
}

function AskCadivorPageInner() {
  const session = useRequireSession();
  const accessToken = session?.access_token || "";
  const searchParams = useSearchParams();
  const router = useRouter();
  const requestedAnalysisId = (searchParams.get("analysis_id") || "").trim();
  const [reports, setReports] = useState<Array<Record<string, unknown>>>([]);
  const [defaultAnalysisId, setDefaultAnalysisId] = useState("");
  const [reportsBusy, setReportsBusy] = useState(true);
  const [reportsError, setReportsError] = useState("");
  const [report, setReport] = useState<Report | null>(null);
  const [reportBusy, setReportBusy] = useState(false);
  const [reportError, setReportError] = useState("");
  const [question, setQuestion] = useState("");
  const [pendingQuestion, setPendingQuestion] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [aiUsage, setAiUsage] = useState<Record<string, unknown> | null>(null);
  const [creditMeterLoaded, setCreditMeterLoaded] = useState(false);
  const [creditMeterError, setCreditMeterError] = useState(false);
  const [creditPackCatalogError, setCreditPackCatalogError] = useState(false);
  const [askCreditPacks, setAskCreditPacks] = useState<Array<Record<string, unknown>>>([]);
  const [canBuyAskCredits, setCanBuyAskCredits] = useState(false);
  const [showAskCreditPacks, setShowAskCreditPacks] = useState(false);
  const [creditCheckoutBusy, setCreditCheckoutBusy] = useState("");
  const [creditCheckoutError, setCreditCheckoutError] = useState("");
  const [creditNotice, setCreditNotice] = useState("");
  const [threadSnapshot, setThreadSnapshot] = useState<ThreadSnapshot>({
    key: "",
    loaded: false,
    threads: [],
  });
  const [activeConversation, setActiveConversation] = useState<{
    analysisId: string;
    threadId: string | null;
  }>({ analysisId: "", threadId: null });
  const [evidenceTab, setEvidenceTab] = useState<EvidenceTab>("evidence");
  const messageListRef = useRef<HTMLDivElement | null>(null);
  const formRef = useRef<HTMLFormElement | null>(null);

  const selectedAnalysisId = requestedAnalysisId || defaultAnalysisId;
  const storageIdentity = session
    ? String(session.user_id || session.email || "").trim().toLowerCase()
    : "";
  const storageKey = storageIdentity
    ? "cadivor_ask_conversations_v1:" + encodeURIComponent(storageIdentity)
    : "";

  const refreshCreditMeter = useCallback(async () => {
    if (!accessToken) return;
    const [usageResult, billingResult] = await Promise.allSettled([
      fetchPlanUsage(accessToken),
      fetchBillingStatus(accessToken),
    ]);
    if (usageResult.status === "fulfilled") {
      const usage = objectValue(objectValue(usageResult.value).usage);
      const credits = objectValue(usage.ai_credits);
      setAiUsage(Object.keys(credits).length ? credits : null);
      setCreditMeterError(Object.keys(credits).length === 0);
    } else {
      setAiUsage(null);
      setCreditMeterError(true);
    }
    if (billingResult.status === "fulfilled") {
      const billing = objectValue(billingResult.value);
      const addons = objectValue(billing.addons);
      const packCatalog = objectValue(addons.ask_cadivor_credits);
      const packs = Array.isArray(packCatalog.packs)
        ? (packCatalog.packs as Array<Record<string, unknown>>)
        : [];
      setAskCreditPacks(packs);
      setCanBuyAskCredits(packCatalog.enabled === true && packs.length > 0);
      setCreditPackCatalogError(false);
    } else {
      setAskCreditPacks([]);
      setCanBuyAskCredits(false);
      setCreditPackCatalogError(true);
    }
    setCreditMeterLoaded(true);
  }, [accessToken]);

  useEffect(() => {
    void refreshCreditMeter();
  }, [refreshCreditMeter]);

  const billingReturn = searchParams.get("billing") || "";
  useEffect(() => {
    if (billingReturn === "usage-pack-success") {
      setCreditNotice("Payment received. Your credit balance is updating.");
      void refreshCreditMeter();
      let attempts = 0;
      const timer = window.setInterval(() => {
        attempts += 1;
        void refreshCreditMeter();
        if (attempts >= 8) window.clearInterval(timer);
      }, 1500);
      return () => window.clearInterval(timer);
    }
    if (billingReturn === "usage-pack-cancel") {
      setCreditNotice("Checkout was canceled. No credits were purchased.");
    }
    return undefined;
  }, [billingReturn, refreshCreditMeter]);

  useEffect(() => {
    if (!accessToken) return;
    let current = true;
    setReportsBusy(true);
    setReportsError("");
    listReports(accessToken)
      .then(({ reports: savedReports }) => {
        if (!current) return;
        const sorted = [...(savedReports || [])]
          .filter((item) => reportId(item))
          .sort(
            (a, b) =>
              Date.parse(String(b.created_at || "")) -
              Date.parse(String(a.created_at || "")),
          );
        setReports(sorted);
        setDefaultAnalysisId((existing) => existing || reportId(sorted[0] || {}));
      })
      .catch((err) => {
        if (current) {
          setReportsError(
            err instanceof Error ? err.message : "Saved BOM reports could not load.",
          );
        }
      })
      .finally(() => {
        if (current) setReportsBusy(false);
      });
    return () => {
      current = false;
    };
  }, [accessToken, session?.user_id]);

  useEffect(() => {
    if (!storageKey) {
      setThreadSnapshot({ key: "", loaded: false, threads: [] });
      return;
    }
    setThreadSnapshot({
      key: storageKey,
      loaded: true,
      threads: readStoredThreads(storageKey),
    });
  }, [storageKey]);

  useEffect(() => {
    setActiveConversation({ analysisId: "", threadId: null });
  }, [storageKey]);

  useEffect(() => {
    if (
      !storageKey ||
      !threadSnapshot.loaded ||
      threadSnapshot.key !== storageKey
    ) {
      return;
    }
    try {
      window.localStorage.setItem(
        storageKey,
        JSON.stringify(threadSnapshot.threads.slice(0, 25)),
      );
    } catch {
      // Conversation history remains available for this page even if browser
      // storage is full or disabled.
    }
  }, [storageKey, threadSnapshot]);

  useEffect(() => {
    if (!accessToken || !selectedAnalysisId) {
      setReport(null);
      setReportBusy(false);
      setReportError("");
      return;
    }
    let current = true;
    setReport(null);
    setReportError("");
    setReportBusy(true);
    fetchReport(selectedAnalysisId, accessToken)
      .then((data) => {
        if (current) setReport(data);
      })
      .catch((err) => {
        if (current) {
          setReportError(
            err instanceof Error
              ? err.message
              : "This saved report could not be opened.",
          );
        }
      })
      .finally(() => {
        if (current) setReportBusy(false);
      });
    return () => {
      current = false;
    };
  }, [accessToken, selectedAnalysisId]);

  const accountThreads =
    threadSnapshot.key === storageKey ? threadSnapshot.threads : [];
  const recentConversations = useMemo(
    () =>
      accountThreads
        .filter((thread) => thread.analysisId === selectedAnalysisId)
        .sort((a, b) => Date.parse(b.updatedAt) - Date.parse(a.updatedAt)),
    [accountThreads, selectedAnalysisId],
  );
  useEffect(() => {
    if (!selectedAnalysisId || !threadSnapshot.loaded || threadSnapshot.key !== storageKey) {
      return;
    }
    if (activeConversation.analysisId === selectedAnalysisId) return;
    setActiveConversation({
      analysisId: selectedAnalysisId,
      threadId: recentConversations[0]?.id || null,
    });
  }, [
    activeConversation.analysisId,
    recentConversations,
    selectedAnalysisId,
    storageKey,
    threadSnapshot.key,
    threadSnapshot.loaded,
  ]);

  const activeThreadId =
    activeConversation.analysisId === selectedAnalysisId
      ? activeConversation.threadId
      : recentConversations[0]?.id || null;
  const activeThread = activeThreadId
    ? recentConversations.find((thread) => thread.id === activeThreadId) || null
    : null;
  const parts = (report?.parts || []) as Array<Record<string, unknown>>;
  const sortedContextRows = useMemo(
    () =>
      [...parts].sort(
        (a, b) => riskRank(riskLabel(a)) - riskRank(riskLabel(b)),
      ),
    [parts],
  );
  const selectedReportRecord = reports.find(
    (item) => reportId(item) === selectedAnalysisId,
  );
  const reportNameLabel = reportName(
    (report as unknown as Record<string, unknown> | null) ||
      selectedReportRecord,
  );
  const allowance = Math.max(0, Number(aiUsage?.allowance || 0));
  const usedCredits = Math.max(0, Number(aiUsage?.used || 0));
  const includedRemaining = aiUsage?.remaining == null
    ? null
    : Math.max(0, Number(aiUsage.remaining || 0));
  const topupCredits = Math.max(0, Number(aiUsage?.topup_credits || 0));
  const isCreditAdmin = aiUsage?.is_admin === true;
  const usagePercent = allowance > 0
    ? Math.min(100, Math.floor((usedCredits / allowance) * 100))
    : 0;
  const resetAt = aiUsage?.reset_at ? new Date(String(aiUsage.reset_at)) : null;
  const resetLabel = resetAt && !Number.isNaN(resetAt.getTime())
    ? resetAt.toLocaleString([], {
        month: "short",
        day: "numeric",
        hour: "numeric",
        minute: "2-digit",
      })
    : "the start of next month";
  const monthlyExhausted = allowance > 0 && includedRemaining === 0;
  const noCreditsAvailable = allowance === 0 && topupCredits === 0;
  const creditWarning = !creditMeterLoaded || creditMeterError || isCreditAdmin
    ? ""
    : monthlyExhausted
      ? (topupCredits > 0
          ? `Monthly credits are used. ${topupCredits.toLocaleString()} prepaid credits remain; monthly credits reset ${resetLabel}.`
          : `You’ve used all monthly credits. They reset ${resetLabel}. Add a one-time pack to keep asking.`)
      : noCreditsAvailable
        ? "This plan has no monthly Ask Cadivor credits. Add a one-time pack to start asking questions."
        : allowance > 0 && usagePercent >= 80
          ? `You’ve used ${usagePercent}% of monthly credits; ${includedRemaining?.toLocaleString() || 0} remain. They reset ${resetLabel}.`
          : allowance > 0 && usagePercent >= 50
            ? `You’ve used ${usagePercent}% of monthly credits; ${includedRemaining?.toLocaleString() || 0} remain. They reset ${resetLabel}.`
            : "";

  useEffect(() => {
    if (messageListRef.current) {
      messageListRef.current.scrollTop = messageListRef.current.scrollHeight;
    }
  }, [activeThread?.messages.length, pendingQuestion, busy]);

  function onReportChange(analysisId: string) {
    if (!analysisId) return;
    setError("");
    setQuestion("");
    setEvidenceTab("evidence");
    router.replace("/ask-cadivor?analysis_id=" + encodeURIComponent(analysisId), {
      scroll: false,
    });
  }

  function updateConversation(next: AskConversation) {
    setThreadSnapshot((current) => {
      if (current.key !== storageKey) return current;
      const threads = [
        next,
        ...current.threads.filter((thread) => thread.id !== next.id),
      ]
        .sort((a, b) => Date.parse(b.updatedAt) - Date.parse(a.updatedAt))
        .slice(0, 25);
      return { ...current, threads };
    });
  }

  async function sendQuestion(value: string) {
    const cleanQuestion = value.trim();
    if (!cleanQuestion || busy || !session || !report || !selectedAnalysisId) return;

    setBusy(true);
    setError("");
    setPendingQuestion(cleanQuestion);
    const priorMessages = activeThread?.messages || [];
    const history = priorMessages
      .slice(-12)
      .map((message) => ({ role: message.role, content: message.content }));
    try {
      const data = await askCadivor(session.access_token, {
        analysis_id: selectedAnalysisId,
        question: cleanQuestion,
        history,
      });
      const answer = cleanUserText(data.answer).trim();
      if (data.ok === false || !answer) {
        throw new Error(
          cleanUserText(data.detail) || "Cadivor could not answer from this report.",
        );
      }
      const now = new Date().toISOString();
      const threadId = activeThread?.id || makeId();
      const userMessage: AskMessage = {
        id: makeId(),
        role: "user",
        content: cleanQuestion,
        createdAt: now,
      };
      const assistantMessage: AskMessage = {
        id: makeId(),
        role: "assistant",
        content: answer,
        createdAt: now,
        grounded: data.grounded === true,
        gap: userFacingAskGap(data.gap),
      };
      const nextThread: AskConversation = {
        id: threadId,
        analysisId: selectedAnalysisId,
        title: activeThread?.title || conversationTitle(cleanQuestion),
        createdAt: activeThread?.createdAt || now,
        updatedAt: now,
        messages: [...priorMessages, userMessage, assistantMessage].slice(-24),
      };
      updateConversation(nextThread);
      setActiveConversation({ analysisId: selectedAnalysisId, threadId });
      setQuestion("");
    } catch (err) {
      setError(
        err instanceof Error ? err.message : "Ask Cadivor could not complete this question.",
      );
      setQuestion(cleanQuestion);
    } finally {
      setPendingQuestion("");
      setBusy(false);
      void refreshCreditMeter();
    }
  }

  async function buyAskCreditPack(packId: string) {
    if (!session || !canBuyAskCredits) return;
    setCreditCheckoutBusy(packId);
    setCreditCheckoutError("");
    try {
      const result = await beginUsageOverageCheckout(
        session.access_token,
        "ask_cadivor",
        packId as "ask_100" | "ask_500" | "ask_1500",
      );
      const url = String(result.checkout?.url || "").trim();
      if (!result.ok || !url) {
        throw new Error(String(result.detail || "Credit checkout could not be opened."));
      }
      window.location.assign(url);
    } catch (err) {
      setCreditCheckoutError(err instanceof Error ? err.message : "Credit checkout could not be opened.");
    } finally {
      setCreditCheckoutBusy("");
    }
  }

  function onSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    void sendQuestion(question);
  }

  function onQuestionKeyDown(event: KeyboardEvent<HTMLTextAreaElement>) {
    if (event.key === "Enter" && !event.shiftKey) {
      event.preventDefault();
      formRef.current?.requestSubmit();
    }
  }

  if (!session) return null;

  const reportsMissingRequestedId =
    Boolean(requestedAnalysisId) &&
    !reportsBusy &&
    !reports.some((item) => reportId(item) === requestedAnalysisId);
  const reportRowsForEvidence = sortedContextRows.slice(0, 5);
  const totalParts = Number(report?.total_parts ?? parts.length);
  const highRiskCount = Number(
    report?.high_risk_count ??
      parts.filter((row) => riskTone(riskLabel(row)) === "high").length,
  );
  const mediumRiskCount = Number(
    report?.medium_risk_count ??
      parts.filter((row) => riskTone(riskLabel(row)) === "medium").length,
  );

  return (
    <Shell session={session}>
    <main className={styles.page}>
      <PageHeader
        meta={PAGE_META.ask}
        actions={
          <>
            <PrimaryLink href="/bom-analyzer">New BOM analysis</PrimaryLink>
            <SecondaryLink href="/reports">Reports</SecondaryLink>
          </>
        }
      />

      {reportsBusy ? <LoadingCard label="Loading saved BOMs…" /> : null}
      {reportsError ? <div className="cv-error" role="alert">{reportsError}</div> : null}

      {!reportsBusy && reports.length > 0 ? (
        <section className={styles.contextBar} aria-label="Selected BOM context">
          <div className={styles.contextCopy}>
            <span className={styles.contextIcon} aria-hidden="true">
              <Icon name="report" />
            </span>
            <div className={styles.contextText}>
              <div className="cv-eyebrow">Ask about a saved report</div>
              <strong>{reportNameLabel}</strong>
              <span>
                {report
                  ? [
                      report.project_name
                        ? userFacingLabel(report.project_name, "Project")
                        : "",
                      report.revision ? "Rev " + String(report.revision) : "",
                      totalParts.toLocaleString() + " BOM rows",
                    ]
                      .filter(Boolean)
                      .join(" · ")
                  : "Select the saved BOM report for your question."}
              </span>
            </div>
          </div>
          <div className={styles.contextActions}>
            <label className={styles.reportSelectLabel}>
              <span>Selected report</span>
              <select
                value={selectedAnalysisId}
                onChange={(event) => onReportChange(event.target.value)}
                disabled={busy || reportBusy}
                aria-label="Select a saved BOM report"
              >
                {reportsMissingRequestedId ? (
                  <option value={requestedAnalysisId}>Report unavailable</option>
                ) : null}
                {reports.map((item) => (
                  <option key={reportId(item)} value={reportId(item)}>
                    {reportOptionLabel(item)}
                  </option>
                ))}
              </select>
            </label>
            {selectedAnalysisId && report ? (
              <Link
                href={"/reports/" + encodeURIComponent(selectedAnalysisId)}
                className="cv-button"
              >
                View report
              </Link>
            ) : null}
          </div>
        </section>
      ) : null}

      {!reportsBusy && !reportsError && !reports.length ? (
        <EmptyState
          icon="report"
          title="No saved BOM reports yet"
          body="Save a BOM analysis first. Ask Cadivor will use the selected report as its source of context."
          action={<PrimaryLink href="/bom-analyzer">Open BOM Analyzer</PrimaryLink>}
        />
      ) : null}

      {reportBusy ? <LoadingCard label="Opening the selected saved report…" /> : null}
      {reportError ? (
        <section className="cv-card pad" role="alert">
          <EmptyState
            icon="report"
            title={reportsMissingRequestedId ? "Saved report unavailable" : "Report could not be opened"}
            body={
              reportsMissingRequestedId
                ? "This report is not available in the current workspace. Select another saved report to continue."
                : reportError
            }
            action={<SecondaryLink href="/reports">Open Reports</SecondaryLink>}
          />
        </section>
      ) : null}

      {report && !reportBusy ? (
        <>
          <div className={styles.workspaceGrid}>
            <section className={styles.chatCard} aria-label="Ask Cadivor conversation">
              <header className={styles.chatHeader}>
                <div className={styles.chatTitleGroup}>
                  <span className={styles.chatMark} aria-hidden="true">
                    <Icon name="spark" />
                  </span>
                  <div className={styles.chatTitleCopy}>
                    <strong>{activeThread?.title || "New conversation"}</strong>
                    <span>{reportNameLabel} · saved analysis context</span>
                  </div>
                </div>
                <div className={styles.chatHeaderActions}>
                  <span className={styles.readyBadge}>
                    <i aria-hidden="true" />
                    {busy ? "Reviewing report" : "Ready"}
                  </span>
                  <button
                    className="cv-button small"
                    type="button"
                    onClick={() => {
                      setActiveConversation({
                        analysisId: selectedAnalysisId,
                        threadId: null,
                      });
                      setError("");
                      setQuestion("");
                    }}
                    disabled={busy}
                  >
                    New conversation
                  </button>
                </div>
              </header>

              <div className={styles.scopeNote}>
                <Icon name="shield" />
                <span>
                  Answers use the selected saved report. Supplier data is not refreshed by this chat.
                </span>
              </div>

              <section className={styles.creditMeter} aria-label="Ask Cadivor credit usage">
                <div className={styles.creditMeterHeader}>
                  <div className={styles.creditMeterTitle}>
                    <strong>Ask Cadivor credits</strong>
                    {!creditMeterLoaded ? (
                      <span>Checking your credit balance…</span>
                    ) : creditMeterError ? (
                      <span>Credit balance could not be loaded. Refresh the page to try again.</span>
                    ) : isCreditAdmin ? (
                      <span>Administrator use is not metered.</span>
                    ) : allowance > 0 ? (
                      <span>{usedCredits.toLocaleString()} of {allowance.toLocaleString()} monthly credits used</span>
                    ) : (
                      <span>No monthly credits are included with this plan.</span>
                    )}
                  </div>
                  {!isCreditAdmin ? (
                    <button
                      className={styles.creditPackToggle}
                      type="button"
                      onClick={() => {
                        setShowAskCreditPacks((open) => !open);
                        setCreditCheckoutError("");
                      }}
                      aria-expanded={showAskCreditPacks}
                      disabled={!creditMeterLoaded}
                    >
                      {!creditMeterLoaded ? "Loading credits…" : showAskCreditPacks ? "Hide packs" : "Get more credits"}
                    </button>
                  ) : null}
                </div>

                {!isCreditAdmin && creditMeterLoaded && !creditMeterError && allowance > 0 ? (
                  <div className={styles.creditMeterProgress}>
                    <div className={styles.creditMeterCounts}>
                      <span>{includedRemaining?.toLocaleString() || 0} monthly credits left</span>
                      <span>{usagePercent}% used</span>
                    </div>
                    <div
                      className={styles.creditMeterTrack}
                      role="progressbar"
                      aria-label="Monthly Ask Cadivor credit usage"
                      aria-valuemin={0}
                      aria-valuemax={100}
                      aria-valuenow={usagePercent}
                    >
                      <span style={{ width: usagePercent + "%" }} />
                    </div>
                  </div>
                ) : null}

                {!isCreditAdmin && creditMeterLoaded && !creditMeterError ? (
                  <div className={styles.creditMeterFoot}>
                    <span>
                      {topupCredits.toLocaleString()} prepaid credits
                      {allowance > 0 ? " · monthly credits are used first" : ""}
                    </span>
                    {allowance > 0 ? <span>Resets {resetLabel}</span> : null}
                  </div>
                ) : null}

                {creditWarning ? (
                  <p
                    className={styles.creditWarning}
                    data-level={monthlyExhausted || noCreditsAvailable ? "exhausted" : usagePercent >= 80 ? "high" : "notice"}
                    role={monthlyExhausted || noCreditsAvailable ? "alert" : "status"}
                  >
                    {creditWarning}
                  </p>
                ) : null}
                {creditNotice ? <p className={styles.creditNotice} role="status">{creditNotice}</p> : null}

                {showAskCreditPacks && !isCreditAdmin ? (
                  <div className={styles.creditPackPanel}>
                    <div className={styles.creditPackPanelHeading}>
                      <strong>One-time credit packs</strong>
                      <span>One-time purchase with no recurring charge. Credits don’t expire; monthly credits are used first.</span>
                    </div>
                    <div className={styles.creditPackGrid}>
                      {askCreditPacks.map((pack) => {
                        const packId = String(pack.id || "");
                        const credits = Math.max(0, Number(pack.credits || 0));
                        const unitPrice = Number(pack.unit_price);
                        const savings = Math.max(0, Number(pack.savings_percent || 0));
                        return (
                          <article className={styles.creditPack} key={packId}>
                            <div className={styles.creditPackTop}>
                              <strong>{String(pack.title || credits.toLocaleString() + " credits")}</strong>
                              {savings > 0 ? <span>Save {savings}%</span> : null}
                            </div>
                            <strong className={styles.creditPackPrice}>{moneyLabel(pack.amount)}</strong>
                            <small>
                              {credits.toLocaleString()} questions
                              {Number.isFinite(unitPrice) ? " · " + (unitPrice * 100).toFixed(2) + "¢ per question" : ""}
                            </small>
                            <button
                              className="cv-button small"
                              type="button"
                              disabled={
                                !canBuyAskCredits ||
                                pack.enabled !== true ||
                                Boolean(creditCheckoutBusy)
                              }
                              onClick={() => void buyAskCreditPack(packId)}
                            >
                              {creditCheckoutBusy === packId ? "Opening checkout…" : "Buy pack"}
                            </button>
                          </article>
                        );
                      })}
                    </div>
                    {creditPackCatalogError ? (
                      <p className={styles.creditPackEligibility}>
                        Credit packs could not load. Refresh this page to try again.
                      </p>
                    ) : askCreditPacks.length === 0 ? (
                      <p className={styles.creditPackEligibility}>
                        Credit packs are temporarily unavailable.
                      </p>
                    ) : null}
                    {creditCheckoutError ? (
                      <p className={styles.creditPackError} role="alert">{creditCheckoutError}</p>
                    ) : null}
                  </div>
                ) : null}
              </section>

              <div
                className={styles.messages}
                ref={messageListRef}
                aria-label="Conversation messages"
                aria-live="polite"
              >
                {activeThread?.messages.length ? (
                  activeThread.messages.map((message) => (
                    <article
                      className={
                        styles.message +
                        (message.role === "user" ? " " + styles.userMessage : "")
                      }
                      key={message.id}
                    >
                      {message.role === "assistant" ? (
                        <span className={styles.messageAvatar} aria-hidden="true">C</span>
                      ) : null}
                      <div className={styles.messageBody}>
                        <div className={styles.messageMeta}>
                          {message.role === "user" ? "You" : "Cadivor"}
                          <span>
                            {message.role === "assistant" && message.grounded
                              ? " · Grounded in saved report"
                              : ""}
                            {" · "}
                            {dateLabel(message.createdAt)}
                          </span>
                        </div>
                        <div
                          className={
                            styles.bubble +
                            (message.role === "user" ? " " + styles.userBubble : "")
                          }
                        >
                          {message.role === "assistant" ? (
                            <div className="cv-ask-answer-body">
                              {formatCadivorAnswer(message.content)}
                            </div>
                          ) : (
                            <p>{message.content}</p>
                          )}
                          {message.role === "assistant" && message.gap ? (
                            <EvidenceNotice gap={message.gap} />
                          ) : null}
                        </div>
                      </div>
                      {message.role === "user" ? (
                        <span className={styles.userAvatar} aria-hidden="true">
                          {(session.email || "You").slice(0, 1).toUpperCase()}
                        </span>
                      ) : null}
                    </article>
                  ))
                ) : (
                  <div className={styles.welcome}>
                    <span className={styles.welcomeIcon} aria-hidden="true">
                      <Icon name="spark" />
                    </span>
                    <h2>What would you like to understand about this BOM?</h2>
                    <p>
                      Ask about risk, lifecycle, supplier coverage, or missing evidence. Cadivor will use the selected saved report.
                    </p>
                  </div>
                )}
                {pendingQuestion ? (
                  <article className={styles.message + " " + styles.userMessage}>
                    <div className={styles.messageBody}>
                      <div className={styles.messageMeta}>You · just now</div>
                      <div className={styles.bubble + " " + styles.userBubble}>
                        <p>{pendingQuestion}</p>
                      </div>
                    </div>
                    <span className={styles.userAvatar} aria-hidden="true">
                      {(session.email || "You").slice(0, 1).toUpperCase()}
                    </span>
                  </article>
                ) : null}
                {busy ? (
                  <div className={styles.reviewing} role="status">
                    <span className={styles.reviewingDot} />
                    Cadivor is reviewing the selected report…
                  </div>
                ) : null}
              </div>

              {!activeThread?.messages.length ? (
                <div className={styles.suggestions}>
                  <span>Try asking</span>
                  <div>
                    {[
                      "What are the highest-risk parts in this BOM?",
                      "What evidence gaps should I review before release?",
                      "Which parts have lifecycle concerns?",
                      "Which components have limited supplier coverage?",
                    ].map((suggestion) => (
                      <button
                        className={styles.suggestion}
                        type="button"
                        key={suggestion}
                        onClick={() => void sendQuestion(suggestion)}
                        disabled={busy}
                      >
                        {suggestion}
                      </button>
                    ))}
                  </div>
                </div>
              ) : null}

              <form className={styles.composerWrap} onSubmit={onSubmit} ref={formRef}>
                {error ? <div className="cv-error" role="alert">{error}</div> : null}
                <div className={styles.composer}>
                  <textarea
                    value={question}
                    onChange={(event) => setQuestion(event.target.value)}
                    onKeyDown={onQuestionKeyDown}
                    placeholder="Ask a question about the selected BOM…"
                    aria-label="Ask a question about the selected BOM"
                    maxLength={2000}
                    rows={2}
                    disabled={busy}
                  />
                  <button
                    className="cv-button primary"
                    type="submit"
                    disabled={busy || !question.trim()}
                  >
                    {busy ? "Reviewing…" : "Ask Cadivor"}
                  </button>
                </div>
                <div className={styles.composerFoot}>
                  <span>Enter to send · Shift+Enter for a new line</span>
                  <span>Answers are based on saved analysis evidence</span>
                </div>
              </form>
            </section>

            <aside className={styles.rightRail} aria-label="Selected report details">
              <section className={styles.sideCard}>
                <h2>Selected report</h2>
                <p className={styles.sideSubtitle}>The saved analysis used as context for this conversation.</p>
                <div className={styles.reportSummary}>
                  <span className={styles.reportFileIcon} aria-hidden="true">
                    <Icon name="report" />
                  </span>
                  <div>
                    <strong>{reportNameLabel}</strong>
                    <span>
                      {[
                        report.project_name
                          ? userFacingLabel(report.project_name, "Project")
                          : "",
                        report.revision ? "Rev " + String(report.revision) : "",
                        report.created_at
                          ? new Date(report.created_at).toLocaleDateString()
                          : "Date not recorded",
                      ]
                        .filter(Boolean)
                        .join(" · ")}
                    </span>
                    <Link href={"/reports/" + encodeURIComponent(selectedAnalysisId)}>
                      Open saved report
                    </Link>
                  </div>
                </div>
                <div className={styles.metrics}>
                  <div><strong>{totalParts.toLocaleString()}</strong><span>BOM rows</span></div>
                  <div><strong>{highRiskCount + mediumRiskCount}</strong><span>High and medium risk</span></div>
                </div>
                {report.health_score != null ? (
                  <p className={styles.healthLine}>
                    Report health · <strong>{Number(report.health_score).toLocaleString()}/100</strong>
                    {report.health_status ? " · " + userFacingLabel(report.health_status, "") : ""}
                  </p>
                ) : null}
              </section>

              <section className={styles.sideCard}>
                <h2>Report context</h2>
                <p className={styles.sideSubtitle}>
                  Rows recorded in the selected report. They are context for review, not new supplier lookups.
                </p>
                <div className={styles.tabs} role="tablist" aria-label="Report context view">
                  <button
                    type="button"
                    role="tab"
                    aria-selected={evidenceTab === "evidence"}
                    onClick={() => setEvidenceTab("evidence")}
                  >
                    Priority rows
                  </button>
                  <button
                    type="button"
                    role="tab"
                    aria-selected={evidenceTab === "bom"}
                    onClick={() => setEvidenceTab("bom")}
                  >
                    BOM rows
                  </button>
                </div>

                {evidenceTab === "evidence" ? (
                  <div className={styles.contextRows} role="tabpanel">
                    {reportRowsForEvidence.length ? (
                      reportRowsForEvidence.map((row, index) => {
                        const mpn = fieldText(row, "MPN", "mpn", "Part Number") || "Part " + (index + 1);
                        const risk = riskLabel(row);
                        const details =
                          fieldText(row, "Risk Reasons", "risk_reasons", "Lifecycle", "lifecycle_status") ||
                          fieldText(row, "Description", "description") ||
                          "No supporting detail is recorded on this row.";
                        const source = fieldText(row, "Source", "source", "evidence_source");
                        return (
                          <article className={styles.contextRow} key={mpn + "-" + index}>
                            <div className={styles.rowHeading}>
                              <strong>{mpn}</strong>
                              <span className={styles.riskPill + " " + styles["tone_" + riskTone(risk)]}>
                                {risk}
                              </span>
                            </div>
                            <p>{details}</p>
                            <span className={styles.rowSource}>
                              {source ? "Recorded source · " + source : "Source not recorded in this row"}
                            </span>
                          </article>
                        );
                      })
                    ) : (
                      <p className={styles.emptyPanel}>This saved report does not include component rows.</p>
                    )}
                    {parts.length > reportRowsForEvidence.length ? (
                      <button
                        type="button"
                        className={styles.showRows}
                        onClick={() => setEvidenceTab("bom")}
                      >
                        View BOM rows
                      </button>
                    ) : null}
                  </div>
                ) : (
                  <div className={styles.tableWrap} role="tabpanel">
                    {parts.length ? (
                      <table className={styles.rowsTable}>
                        <thead>
                          <tr><th>Part</th><th>Lifecycle</th><th>Risk</th></tr>
                        </thead>
                        <tbody>
                          {parts.slice(0, 12).map((row, index) => {
                            const mpn =
                              fieldText(row, "MPN", "mpn", "Part Number") || "Part " + (index + 1);
                            const lifecycle =
                              fieldText(row, "Lifecycle", "lifecycle_status", "Lifecycle Status") ||
                              "Not reported";
                            const risk = riskLabel(row);
                            return (
                              <tr key={mpn + "-" + index}>
                                <td title={mpn}>{mpn}</td>
                                <td>{lifecycle}</td>
                                <td>
                                  <span className={styles.riskPill + " " + styles["tone_" + riskTone(risk)]}>
                                    {risk}
                                  </span>
                                </td>
                              </tr>
                            );
                          })}
                        </tbody>
                      </table>
                    ) : (
                      <p className={styles.emptyPanel}>This saved report does not include component rows.</p>
                    )}
                    {parts.length > 12 ? (
                      <p className={styles.tableMore}>
                        Showing 12 of {parts.length.toLocaleString()} rows. Open the report to review the full BOM.
                      </p>
                    ) : null}
                  </div>
                )}
              </section>

              <section className={styles.sideCard}>
                <div className={styles.recentHeading}>
                  <div>
                    <h2>Recent conversations</h2>
                    <p className={styles.sideSubtitle}>Pick up a previous question for this report.</p>
                  </div>
                  <button
                    className="cv-button small"
                    type="button"
                    onClick={() =>
                      setActiveConversation({
                        analysisId: selectedAnalysisId,
                        threadId: null,
                      })
                    }
                    disabled={busy}
                  >
                    New
                  </button>
                </div>
                {recentConversations.length ? (
                  <div className={styles.recentList}>
                    {recentConversations.slice(0, 5).map((thread) => (
                      <div className={styles.recentRow} key={thread.id}>
                        <div>
                          <strong>{thread.title}</strong>
                          <span>{dateLabel(thread.updatedAt)}</span>
                        </div>
                        <button
                          type="button"
                          aria-label={"Open conversation: " + thread.title}
                          aria-current={thread.id === activeThread?.id ? "true" : undefined}
                          disabled={busy}
                          onClick={() =>
                            setActiveConversation({
                              analysisId: selectedAnalysisId,
                              threadId: thread.id,
                            })
                          }
                        >
                          {thread.id === activeThread?.id ? "Open" : "Resume"}
                        </button>
                      </div>
                    ))}
                  </div>
                ) : (
                  <p className={styles.emptyPanel}>Your completed conversations for this report will appear here.</p>
                )}
                <p className={styles.storageNote}>Conversation history is saved in this browser for this account.</p>
              </section>
            </aside>
          </div>
          <p className={styles.footerNote}>
            Answers stay tied to this report revision. Re-run the BOM analysis when you need a newer supplier snapshot.
          </p>
        </>
      ) : null}
    </main>
    </Shell>
  );
}

export default function AskCadivorPage() {
  return (
    <Suspense fallback={<LoadingCard label="Opening Ask Cadivor…" />}>
      <AskCadivorPageInner />
    </Suspense>
  );
}
