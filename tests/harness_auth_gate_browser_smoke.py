#!/usr/bin/env python3
"""Browser-level production-path auth continuity smoke harness.

Usage:
  /opt/anaconda3/bin/python tests/harness_auth_gate_browser_smoke.py

Launches real ``streamlit_app.py``. Provider-boundary doubles are injected only
via test-only process configuration: PYTHONPATH prepends
``tests/smoke_pythonpath`` (sitecustomize). Production never loads that path.
Captures frames under /tmp/cadivor_auth_gate_smoke/.
"""
from __future__ import annotations

import json
import os
import signal
import subprocess
import sys
import time
from pathlib import Path
from urllib.parse import parse_qs, unquote_plus, urlparse

ROOT = Path(__file__).resolve().parents[1]
OUT = Path("/tmp/cadivor_auth_gate_smoke")
PORT = int(os.environ.get("CADIVOR_AUTH_SMOKE_PORT") or "8525")
MOCK_EMAIL = "auth-smoke@cadivor.test"
MOCK_PASSWORD = "cadivor-auth-smoke"
STREAMLIT_PY = str(ROOT / "venv" / "bin" / "python")
if not Path(STREAMLIT_PY).exists():
    STREAMLIT_PY = sys.executable
SMOKE_APP = str(ROOT / "streamlit_app.py")
SMOKE_PYTHONPATH = str(ROOT / "tests" / "smoke_pythonpath")
SAMPLE_MS = 100
AUTH_SURFACE_MAX_SECONDS_WITHOUT_PROGRESS = 2.0

# Full authenticated nav circuit, ending back on Dashboard.
# Includes Dashboard → BOM Analyzer → Compare Parts to catch chrome/content races.
AUTH_ROUTE_CIRCUIT = (
    "Dashboard",
    "BOM Analyzer",
    "Compare Parts",
    "Alternative Finder",
    "Datasheet Q&A",
    "Procurement Advisor",
    "Dashboard",
)

ROUTE_NAV_SLUGS = {
    "Dashboard": "dashboard",
    "BOM Analyzer": "bom",
    "Alternative Finder": "alternatives",
    "Datasheet Q&A": "datasheet-qa",
    "Compare Parts": "compare",
    "Procurement Advisor": "procurement",
}

# Distinctive main-canvas copy — must appear before a route is considered settled.
# Sidebar labels alone are not enough (every route name is always in the nav).
ROUTE_CONTENT_MARKERS = {
    "Dashboard": ("Monitor portfolio health", "Welcome,"),
    # Include the first-painted hero copy so settled/inflight checks lock as soon as
    # real BOM body mounts (not only the later upload-path cards).
    "BOM Analyzer": (
        "Turn a parts list into an engineering risk decision",
        "Upload engineering BOM",
        "Choose how to begin",
        "Analyze your BOM",
    ),
    "Alternative Finder": ("Choose a better replacement", "Find Alternatives"),
    "Datasheet Q&A": ("Ask Cadivor about your datasheet", "Upload datasheet"),
    "Compare Parts": ("Compare any two parts", "Part A"),
    "Procurement Advisor": ("Procurement Advisor", "Action Needed"),
}

# Main-canvas markers that must not appear when chrome is already on the target.
ROUTE_FORBIDDEN_STALE_MARKERS = {
    "BOM Analyzer": ("Monitor portfolio health",),
    "Compare Parts": ("Monitor portfolio health", "Upload engineering BOM"),
    "Alternative Finder": ("Monitor portfolio health", "Upload engineering BOM"),
    "Datasheet Q&A": ("Monitor portfolio health", "Upload engineering BOM"),
    "Procurement Advisor": ("Monitor portfolio health", "Upload engineering BOM"),
    "Dashboard": ("Upload engineering BOM", "Compare any two parts"),
}


def _assert_not_blank_topbar(html: str, label: str) -> None:
    if "cv-startup-shell-topbar" in html:
        raise AssertionError(f"{label}: fake startup topbar present")
    has_gate = 'data-auth-gate="' in html or "cadivor-auth-gate" in html
    has_brand = "Cadivor" in html
    has_login = "Login" in html or "Sign in" in html or "password" in html.lower()
    has_ready = (
        "Dashboard" in html
        or "Engineering workspace" in html
        or "cv-foundation-topbar" in html
    )
    if not (has_gate or has_brand or has_login or has_ready):
        raise AssertionError(f"{label}: empty/unknown frame without gate or brand")


_MARKUP_INDICATORS = (
    "<div",
    "<style",
    "<span",
    "class=",
    "cv-",
    "</",
    "unsafe_allow_html",
)


def _assert_no_visible_markup(page, label: str) -> None:
    """Visible page text must never contain raw HTML / CSS / component markup."""
    try:
        visible = str(page.inner_text("body") or "")
    except Exception as exc:
        raise AssertionError(f"{label}: could not read visible text ({exc})") from exc
    lowered = visible.casefold()
    for token in _MARKUP_INDICATORS:
        if token.casefold() in lowered:
            raise AssertionError(
                f"{label}: visible text contains markup indicator {token!r}"
            )


def _viewport_probe(page) -> dict:
    return page.evaluate(
        """() => {
          const text = (document.body && document.body.innerText || '').replace(/\\s+/g, ' ').trim();
          const bg = window.getComputedStyle(document.body).backgroundColor || '';
          const visiblyPainted = (el) => {
            if (!el) return false;
            const style = window.getComputedStyle(el);
            const rect = el.getBoundingClientRect();
            if (
              style.display === 'none' ||
              style.visibility === 'hidden' ||
              Number(style.opacity || '1') === 0 ||
              rect.height < 2 ||
              rect.width < 2
            ) {
              return false;
            }
            return true;
          };
          const gateVisiblyPainted = (el) => {
            if (!visiblyPainted(el)) return false;
            // Streamlit keeps prior-run gate markers clipped / aria-hidden / stale.
            if (el.getAttribute('aria-hidden') === 'true') return false;
            if (el.closest && el.closest('[data-stale="true"]')) return false;
            const rect = el.getBoundingClientRect();
            if (rect.width <= 2 && rect.height <= 2) return false;
            return true;
          };
          const gateNodes = Array.from(document.querySelectorAll(
            '.cv-auth-gate, .cv-auth-gate-card, [data-testid="cadivor-auth-gate"], [data-auth-gate]'
          ));
          const visibleGate = gateNodes.some((el) => gateVisiblyPainted(el));
          const gateEl = gateNodes.find((el) => gateVisiblyPainted(el))
            || document.querySelector('[data-auth-gate]');
          const gateKind = (gateEl && gateEl.getAttribute('data-auth-gate')) || '';
          const authCard = document.querySelector(
            '.st-key-cadivor_auth_card, [class*="st-key-cadivor_auth_card"]'
          );
          const authCardVisible = visiblyPainted(authCard);
          const authCardText = authCardVisible
            ? ((authCard && authCard.innerText) || '').replace(/\\s+/g, ' ').trim()
            : '';
          const cardSigningIn = authCardVisible && /Signing you in/i.test(authCardText);
          const emptyAuthCard = authCardVisible && authCardText.length < 8;
          const gateCard = document.querySelector('.cv-auth-gate-card');
          const gateCardVisible = gateVisiblyPainted(gateCard);
          const gateCardText = gateCardVisible
            ? ((gateCard && gateCard.innerText) || '').replace(/\\s+/g, ' ').trim()
            : '';
          const emptyGateCard = gateCardVisible && gateCardText.length < 8;
          const pageContentReady = !!document.querySelector('[data-cadivor-page-content]');
          const topbar = document.querySelector(
            '.cv-foundation-topbar:not(.cv-foundation-continuity)'
          );
          const nav = document.querySelector(
            '.st-key-cv_foundation_navigation, [class*="st-key-cv_foundation_navigation"]'
          );
          const continuityOnly = !visiblyPainted(topbar) && !!document.querySelector(
            '.cv-foundation-continuity, [data-testid="cadivor-continuity-shell"]'
          );
          const hasLogin = gateKind === 'login' || /\\bLogin\\b|Sign in|password/i.test(text);
          const hasShell = !!(visiblyPainted(topbar) && visiblyPainted(nav));
          const centeredLoader = Array.from(document.querySelectorAll(
            '.cv-auth-gate-card, [data-testid="cadivor-auth-gate"] .cv-auth-card, .cv-boot-card'
          )).some((el) => {
            if (!gateVisiblyPainted(el)) return false;
            const rect = el.getBoundingClientRect();
            const cx = rect.left + rect.width / 2;
            const cy = rect.top + rect.height / 2;
            return Math.abs(cx - window.innerWidth / 2) < 220 &&
                   Math.abs(cy - window.innerHeight / 2) < 220;
          });
          const duplicateAuthSurface =
            authCardVisible && visibleGate && gateKind === 'authenticating';
          const blankCanvas =
            text.length < 8 &&
            !hasLogin &&
            !hasShell &&
            (/rgb\\(\\s*255\\s*,\\s*255\\s*,\\s*255\\s*\\)/.test(bg) ||
             /rgb\\(\\s*0\\s*,\\s*0\\s*,\\s*0\\s*\\)/.test(bg) ||
             bg === 'rgba(0, 0, 0, 0)' ||
             !bg);
          return {
            textLen: text.length,
            textPreview: text.slice(0, 180),
            bg,
            hasLogin,
            hasShell,
            visibleGate,
            gateKind,
            continuityOnly,
            centeredLoader,
            blankCanvas,
            signingIn: /Signing you in|Restoring your session/i.test(text),
            authCardVisible,
            cardSigningIn,
            emptyAuthCard,
            emptyGateCard,
            pageContentReady,
            duplicateAuthSurface,
          };
        }"""
    )


def _assert_auth_surface_invariants(page, label: str, *, auth_surface_started_at: float | None = None) -> None:
    """Fail on empty auth cards, duplicate surfaces, or stalled auth without progress."""
    probe = _viewport_probe(page)
    if probe.get("blankCanvas"):
        raise AssertionError(
            f"{label}: blank black/white frame "
            f"(bg={probe.get('bg')!r} preview={probe.get('textPreview')!r})"
        )
    if probe.get("emptyAuthCard"):
        raise AssertionError(
            f"{label}: .st-key-cadivor_auth_card visible with no readable text"
        )
    if probe.get("emptyGateCard"):
        raise AssertionError(
            f"{label}: .cv-auth-gate-card visible with no readable text"
        )
    if probe.get("duplicateAuthSurface"):
        raise AssertionError(
            f"{label}: auth card and .cv-auth-gate authenticating surface both visible"
        )
    auth_surface = bool(
        probe.get("authCardVisible")
        or (
            probe.get("visibleGate")
            and probe.get("gateKind") in {"boot", "authenticating", "login", "error"}
        )
    )
    if (
        auth_surface
        and not probe.get("hasShell")
        and not probe.get("signingIn")
        and not probe.get("hasLogin")
        and auth_surface_started_at is not None
        and (time.monotonic() - auth_surface_started_at)
        > AUTH_SURFACE_MAX_SECONDS_WITHOUT_PROGRESS
    ):
        raise AssertionError(
            f"{label}: auth surface visible >{AUTH_SURFACE_MAX_SECONDS_WITHOUT_PROGRESS}s "
            f"without Signing you in… / Login / recoverable error "
            f"(preview={probe.get('textPreview')!r})"
        )
    # URL/sidebar/topbar/content agreement is enforced by _assert_settled_route
    # once a route is expected to be settled — not on every in-flight nav frame.



def _assert_no_forbidden_loading_ui(page, label: str, *, require_shell: bool = False) -> None:
    """Fail on blank/black, placeholder cards, or main-canvas workspace loading cards."""
    probe = _viewport_probe(page)
    if probe.get("blankCanvas"):
        raise AssertionError(
            f"{label}: blank black/white full-page frame "
            f"(bg={probe.get('bg')!r} preview={probe.get('textPreview')!r})"
        )
    report = page.evaluate(
        """() => {
          const ignoreSel =
            '[class*="st-key-cv_foundation_navigation"], .cv-foundation-topbar, '
            + '[class*="st-key-cv_foundation_profile"], .cv-foundation-plan-card, '
            + '[data-testid="stSidebar"], .cv-route-loading, '
            + '[data-cadivor-route-loading], [data-testid="cadivor-route-loading"]';
          const inIgnored = (el) => !!(el.closest && el.closest(ignoreSel));
          const visible = (el) => {
            const style = window.getComputedStyle(el);
            const rect = el.getBoundingClientRect();
            return !(
              style.display === 'none' ||
              style.visibility === 'hidden' ||
              Number(style.opacity || '1') === 0 ||
              rect.height < 2 ||
              rect.width < 2
            );
          };
          const placeholders = Array.from(document.querySelectorAll(
            '[data-testid="cadivor-main-content-placeholder"], '
            + '.cv-main-content-placeholder, .cv-main-content-placeholder-card'
          )).filter((el) => !inIgnored(el) && visible(el));
          // Main-canvas cards only (exclude foundation chrome / plan card).
          const mainRoot = document.querySelector('section[data-testid="stMain"]') || document.body;
          const candidates = Array.from(mainRoot.querySelectorAll('div')).filter((el) => {
            if (inIgnored(el)) return false;
            if (!visible(el)) return false;
            const rect = el.getBoundingClientRect();
            // Card-sized region in the content column (right of the rail).
            if (rect.left < 200) return false;
            if (rect.height < 70 || rect.height > 360) return false;
            if (rect.width < 220 || rect.width > 1100) return false;
            const text = (el.innerText || '').replace(/\\s+/g, ' ').trim();
            // Exact removed placeholder copy, or a card whose primary text is the
            // loading line (not the sidebar plan summary buried in a huge node).
            if (/Loading your workspace/i.test(text)) return true;
            if (!/^Dashboard\\s+Loading workspace/i.test(text)
                && !/^Loading workspace\\b/i.test(text)) {
              return false;
            }
            return text.length < 120;
          });
          const tops = [];
          const samples = [];
          for (const el of candidates) {
            const top = Math.round(el.getBoundingClientRect().top);
            if (tops.some((t) => Math.abs(t - top) < 8)) continue;
            tops.push(top);
            samples.push((el.innerText || '').replace(/\\s+/g, ' ').trim().slice(0, 80));
          }
          return {
            placeholderCount: placeholders.length,
            loadingCardTops: tops,
            loadingCardCount: tops.length,
            samples,
          };
        }"""
    )
    if report.get("placeholderCount", 0) > 0:
        raise AssertionError(
            f"{label}: main-content placeholder still mounted "
            f"(count={report.get('placeholderCount')})"
        )
    if require_shell or probe.get("hasShell"):
        if report.get("loadingCardCount", 0) > 0:
            raise AssertionError(
                f"{label}: main-canvas Loading workspace card present "
                f"(tops={report.get('loadingCardTops')!r} samples={report.get('samples')!r})"
            )
        if report.get("loadingCardCount", 0) >= 2:
            raise AssertionError(
                f"{label}: duplicate loading cards "
                f"(tops={report.get('loadingCardTops')!r})"
            )


def _assert_visible_branded_surface(page, label: str) -> None:
    """Fail if the viewport has neither Login nor the authenticated foundation shell."""
    _assert_no_forbidden_loading_ui(page, label)
    probe = _viewport_probe(page)
    if probe.get("blankCanvas"):
        raise AssertionError(
            f"{label}: blank black/white frame "
            f"(bg={probe.get('bg')!r} preview={probe.get('textPreview')!r})"
        )
    if probe.get("hasLogin") or probe.get("hasShell"):
        return
    # During the brief authenticating transition, a branded gate card is allowed.
    if probe.get("visibleGate") and probe.get("gateKind") in {
        "boot",
        "authenticating",
        "error",
        "login",
    }:
        return
    body = " ".join((page.inner_text("body") or "").split())
    if len(body) < 8:
        raise AssertionError(f"{label}: blank viewport (no visible text)")
    raise AssertionError(
        f"{label}: viewport has neither Login nor authenticated foundation shell "
        f"(preview={probe.get('textPreview')!r})"
    )


def _assert_authenticated_continuity(page, label: str, *, allow_authenticating: bool = False) -> None:
    """Post-login invariant: shell stays; login/boot must not overlay settled content."""
    _assert_no_forbidden_loading_ui(page, label)
    _assert_auth_surface_invariants(page, label)
    probe = _viewport_probe(page)
    if probe.get("blankCanvas"):
        raise AssertionError(f"{label}: blank black/white authenticated frame")
    if not probe.get("hasShell"):
        if allow_authenticating and probe.get("signingIn"):
            return
        raise AssertionError(
            f"{label}: authenticated foundation shell missing "
            f"(preview={probe.get('textPreview')!r})"
        )
    # Progress gate may remain until page content marker is present.
    if probe.get("signingIn") and not probe.get("pageContentReady"):
        return
    if probe.get("visibleGate") and probe.get("gateKind") in {
        "boot",
        "authenticating",
        "login",
        "error",
    }:
        if probe.get("gateKind") == "authenticating" and not probe.get("pageContentReady"):
            return
        raise AssertionError(
            f"{label}: visible .cv-auth-gate still present after shell+content "
            f"(kind={probe.get('gateKind')!r})"
        )
    if (
        (probe.get("centeredLoader") or probe.get("signingIn"))
        and probe.get("pageContentReady")
    ):
        raise AssertionError(
            f"{label}: centered auth/boot loader still visible after page content ready"
        )


def _assert_no_continuity_skeleton_above_content(page, label: str) -> None:
    offenders = page.evaluate(
        """() => {
          const selectors = [
            '[data-testid="cadivor-continuity-shell"]',
            '.cv-foundation-continuity',
            '.cv56-skeleton-page',
          ];
          const hits = [];
          for (const sel of selectors) {
            let nodes = [];
            try { nodes = Array.from(document.querySelectorAll(sel)); } catch (e) { continue; }
            for (const el of nodes) {
              const style = window.getComputedStyle(el);
              const rect = el.getBoundingClientRect();
              const hidden =
                style.display === 'none' ||
                style.visibility === 'hidden' ||
                Number(style.opacity || '1') === 0 ||
                rect.height < 1 ||
                rect.width < 1;
              if (hidden) continue;
              if (rect.height > 8 && rect.top < 120) {
                hits.push({ sel, top: rect.top, height: rect.height });
              }
            }
          }
          return hits;
        }"""
    )
    if offenders:
        raise AssertionError(f"{label}: continuity/skeleton still occupying layout {offenders!r}")


def _assert_login_handoff_frame(page, label: str, *, auth_surface_started_at: float | None = None) -> None:
    """Fail if the Login→shell handoff exposes a frame with neither Login/progress nor shell."""
    _assert_no_forbidden_loading_ui(page, label)
    _assert_auth_surface_invariants(
        page, label, auth_surface_started_at=auth_surface_started_at
    )
    probe = _viewport_probe(page)
    has_progress = bool(
        probe.get("signingIn")
        or probe.get("cardSigningIn")
        or probe.get("gateKind") in {"authenticating", "boot"}
        or (
            probe.get("visibleGate")
            and probe.get("gateKind") in {"authenticating", "boot", "login", "error"}
        )
    )
    if probe.get("hasShell") or probe.get("hasLogin") or has_progress:
        # Shell may mount while Signing you in… remains until page content.
        # Fail only when a Login/boot/error card overlays the shell without progress.
        if probe.get("hasShell") and (
            (
                probe.get("visibleGate")
                and probe.get("gateKind") in {"boot", "login", "error"}
            )
            or (
                probe.get("centeredLoader")
                and not probe.get("signingIn")
                and probe.get("gateKind") != "authenticating"
                and not probe.get("cardSigningIn")
            )
        ):
            raise AssertionError(
                f"{label}: gate/boot card still visible after foundation shell mounted"
            )
        return
    if probe.get("blankCanvas"):
        raise AssertionError(
            f"{label}: white/blank handoff frame "
            f"(bg={probe.get('bg')!r} preview={probe.get('textPreview')!r})"
        )
    raise AssertionError(
        f"{label}: handoff frame has neither Login/progress nor foundation shell "
        f"(preview={probe.get('textPreview')!r})"
    )


def _url_page_param(page) -> str:
    parsed = urlparse(page.url)
    values = parse_qs(parsed.query).get("page") or []
    if not values:
        return ""
    return unquote_plus(str(values[0] or "")).strip()


def _route_sync_probe(page, route: str) -> dict:
    slug = ROUTE_NAV_SLUGS[route]
    markers = ROUTE_CONTENT_MARKERS[route]
    stale = ROUTE_FORBIDDEN_STALE_MARKERS.get(route, ())
    return page.evaluate(
        """({ route, slug, markers, stale }) => {
          const main = document.querySelector('section[data-testid="stMain"]') || document.body;
          const text = (main && main.innerText || '').replace(/\\s+/g, ' ').trim();
          const topbar = document.querySelector(
            '.cv-foundation-page-context strong'
          );
          const topbarLabel = (topbar && topbar.innerText || '').replace(/\\s+/g, ' ').trim();
          const navBtn = document.querySelector(
            '.st-key-cv_foundation_nav_' + slug + ' button, '
            + '[class*="st-key-cv_foundation_nav_' + slug + '"] button'
          );
          let selected = false;
          if (navBtn) {
            const kind = (navBtn.getAttribute('kind') || '').toLowerCase();
            const testid = (navBtn.getAttribute('data-testid') || '').toLowerCase();
            selected = kind === 'primary' || testid.includes('primary');
          }
          const loadingEl = document.querySelector(
            '[data-cadivor-route-loading], [data-testid="cadivor-route-loading"], .cv-route-loading'
          );
          let loadingVisible = false;
          let loadingRoute = '';
          if (loadingEl) {
            const style = window.getComputedStyle(loadingEl);
            const rect = loadingEl.getBoundingClientRect();
            loadingVisible = !(
              style.display === 'none' ||
              style.visibility === 'hidden' ||
              Number(style.opacity || '1') === 0 ||
              rect.height < 2
            );
            loadingRoute = (
              loadingEl.getAttribute('data-cadivor-route-loading') || ''
            ).trim();
          }
          const contentOk = markers.some((m) => text.includes(m));
          const loadingOk = loadingVisible && loadingRoute === route;
          const staleHit = stale.find((m) => text.includes(m)) || '';
          // Blank main: foundation chrome present but neither body markers nor
          // explicit target-route loading surface.
          const hasFoundation = !!(
            document.querySelector('.cv-foundation-topbar:not(.cv-foundation-continuity)')
            || document.querySelector(
                 '.st-key-cv_foundation_navigation, [class*="st-key-cv_foundation_navigation"]'
               )
          );
          const blankMain = hasFoundation && !contentOk && !loadingOk && text.length < 40;
          return {
            topbarLabel,
            selected,
            contentOk,
            loadingOk,
            loadingVisible,
            loadingRoute,
            blankMain,
            staleHit,
            textPreview: text.slice(0, 220),
            hasStaleAf: route !== 'Alternative Finder' && text.includes('Choose a better replacement'),
            hasStaleCompare: route !== 'Compare Parts' && text.includes('Compare any two parts'),
            hasStaleQa: route !== 'Datasheet Q&A' && text.includes('Ask Cadivor about your datasheet'),
            hasStaleDashboard: route !== 'Dashboard' && text.includes('Monitor portfolio health'),
          };
        }""",
        {"route": route, "slug": slug, "markers": list(markers), "stale": list(stale)},
    )


def _assert_in_flight_route_frame(page, route: str, label: str) -> None:
    """Every sampled nav frame: chrome agrees, main is not blank, no stale body."""
    _assert_no_visible_markup(page, label)
    probe = _viewport_probe(page)
    if probe.get("blankCanvas"):
        raise AssertionError(
            f"{label}: blank main/full-page canvas during route transition "
            f"(bg={probe.get('bg')!r} preview={probe.get('textPreview')!r})"
        )
    sync = _route_sync_probe(page, route)
    url_page = _url_page_param(page)
    url_ok = url_page == route or (route == "Dashboard" and url_page in {"", "Dashboard"})
    chrome_committed = (
        sync.get("topbarLabel") == route
        or sync.get("selected")
        or url_ok
    )
    if not chrome_committed:
        # Early click frames may not have flipped chrome yet — still forbid blank.
        if sync.get("blankMain"):
            raise AssertionError(
                f"{label}: blank main before chrome commit "
                f"(preview={sync.get('textPreview')!r})"
            )
        return
    # Once topbar shows the target, main must be target content or explicit loading.
    if sync.get("topbarLabel") == route:
        if sync.get("blankMain"):
            raise AssertionError(
                f"{label}: blank main while {route!r} chrome is active "
                f"(preview={sync.get('textPreview')!r})"
            )
        if not sync.get("contentOk") and not sync.get("loadingOk"):
            raise AssertionError(
                f"{label}: {route!r} chrome without target content or in-shell loading "
                f"(topbar={sync.get('topbarLabel')!r} preview={sync.get('textPreview')!r})"
            )
        if sync.get("staleHit") and not sync.get("loadingOk"):
            raise AssertionError(
                f"{label}: stale content {sync.get('staleHit')!r} under {route!r} chrome "
                f"(preview={sync.get('textPreview')!r})"
            )
        if sync.get("hasStaleDashboard") and not sync.get("loadingOk"):
            raise AssertionError(
                f"{label}: Dashboard content visible while {route!r} chrome is active "
                f"(preview={sync.get('textPreview')!r})"
            )
    elif sync.get("selected") and url_ok:
        # Sidebar + URL flipped before topbar markdown — still forbid blank/stale.
        if sync.get("blankMain"):
            raise AssertionError(
                f"{label}: blank main while sidebar/URL show {route!r} "
                f"(preview={sync.get('textPreview')!r})"
            )
        if sync.get("hasStaleDashboard") and not sync.get("loadingOk"):
            raise AssertionError(
                f"{label}: Dashboard content with {route!r} sidebar/URL "
                f"(preview={sync.get('textPreview')!r})"
            )


def _dashboard_heading_layout_probe(page) -> dict:
    """Measure Dashboard heading geometry and leftover auth hosts above it."""
    return page.evaluate(
        """() => {
          const dash =
            document.querySelector('.cv672-dashboard-heading, .cv-page-header')
            || Array.from(
                 document.querySelectorAll(
                   'section[data-testid="stMain"] h1, section[data-testid="stMain"] h2'
                 )
               ).find((el) => /^\\s*Dashboard\\s*$/i.test((el.innerText || '').trim()));
          const dashTop = dash ? Math.round(dash.getBoundingClientRect().top) : null;
          const authHosts = [];
          const selectors = [
            '.st-key-cadivor_auth_card',
            '[class*="st-key-cadivor_auth_card"]',
            '.cv-auth-card-progress',
            '.cv-auth-gate',
            '.cv-auth-gate-card',
            '[data-testid="cadivor-auth-gate"]',
            '.st-key-cadivor_browser_navigation_bridge',
            '[class*="st-key-cadivor_browser_navigation_bridge"]',
          ];
          const isHost = (el) => {
            if (!el || !el.getAttribute) return false;
            if (el.getAttribute('data-testid') === 'stElementContainer') return true;
            const cls = (el.className || '').toString();
            return (
              cls.includes('element-container')
              || cls.includes('st-key-cadivor_auth_card')
              || cls.includes('st-key-cadivor_browser_navigation_bridge')
            );
          };
          for (const sel of selectors) {
            for (const el of document.querySelectorAll(sel)) {
              let cur = el;
              for (let depth = 0; depth < 5 && cur; depth += 1) {
                if (!isHost(cur) && depth > 0) {
                  cur = cur.parentElement;
                  continue;
                }
                const style = window.getComputedStyle(cur);
                const rect = cur.getBoundingClientRect();
                const inFlow =
                  style.display !== 'none'
                  && style.position !== 'fixed'
                  && style.position !== 'absolute'
                  && rect.height > 0.5;
                // Ignore giant page wrappers; only blank host bands matter.
                if (inFlow && rect.height < 220) {
                  authHosts.push({
                    sel,
                    depth,
                    height: Math.round(rect.height),
                    top: Math.round(rect.top),
                    display: style.display,
                    cls: (cur.className || '').toString().slice(0, 120),
                  });
                }
                cur = cur.parentElement;
              }
            }
          }
          return {
            dashTop,
            dashText: dash
              ? (dash.innerText || '').replace(/\\s+/g, ' ').trim().slice(0, 120)
              : '',
            authHostsInFlow: authHosts,
            hasPageContent: !!document.querySelector('[data-cadivor-page-content]'),
            hasFoundation: !!(
              document.querySelector('.cv-foundation-topbar:not(.cv-foundation-continuity)')
              || document.querySelector(
                   '.st-key-cv_foundation_navigation, [class*="st-key-cv_foundation_navigation"]'
                 )
            ),
          };
        }"""
    )


def _assert_no_blank_auth_hosts_above_dashboard(page, label: str) -> None:
    probe = _dashboard_heading_layout_probe(page)
    if not probe.get("hasPageContent") or not probe.get("hasFoundation"):
        raise AssertionError(
            f"{label}: shell/page-content markers missing during layout probe "
            f"(foundation={probe.get('hasFoundation')} content={probe.get('hasPageContent')})"
        )
    leftover = probe.get("authHostsInFlow") or []
    if leftover:
        raise AssertionError(
            f"{label}: blank/empty auth (or bridge) host still in-flow above Dashboard: "
            f"{leftover[:8]!r}"
        )


def _assert_first_login_matches_reload_dashboard_geometry(
    page,
    *,
    frames_dir: Path,
    tolerance_px: float = 4.0,
) -> None:
    """Cold first login Dashboard top must match a manual reload within tolerance."""
    page.wait_for_timeout(400)
    first = _dashboard_heading_layout_probe(page)
    (frames_dir / "04_first_login_layout.json").write_text(
        json.dumps(first, indent=2), encoding="utf-8"
    )
    page.screenshot(path=str(frames_dir / "04_first_login_layout.png"), full_page=True)
    _assert_no_blank_auth_hosts_above_dashboard(page, "first_login_layout")
    first_top = first.get("dashTop")
    if first_top is None:
        raise AssertionError("first_login_layout: Dashboard heading not found")

    page.reload(wait_until="domcontentloaded", timeout=90000)
    for i in range(200):
        try:
            _assert_settled_route(page, "Dashboard", f"reload_settle_{i}")
            break
        except AssertionError:
            page.wait_for_timeout(SAMPLE_MS)
    else:
        raise AssertionError("reload_settle: Dashboard never settled after reload")

    page.wait_for_timeout(400)
    reload = _dashboard_heading_layout_probe(page)
    (frames_dir / "04_reload_layout.json").write_text(
        json.dumps(reload, indent=2), encoding="utf-8"
    )
    page.screenshot(path=str(frames_dir / "04_reload_layout.png"), full_page=True)
    _assert_no_blank_auth_hosts_above_dashboard(page, "reload_layout")
    reload_top = reload.get("dashTop")
    if reload_top is None:
        raise AssertionError("reload_layout: Dashboard heading not found")
    delta = abs(float(first_top) - float(reload_top))
    if delta > tolerance_px:
        raise AssertionError(
            f"first_login_layout: Dashboard top {first_top}px differs from reload "
            f"{reload_top}px by {delta}px (max {tolerance_px}px)"
        )


def _assert_settled_route(page, route: str, label: str) -> None:
    """Require URL page, selected sidebar, topbar label, and main content to agree."""
    _assert_no_visible_markup(page, label)
    _assert_authenticated_continuity(page, label)
    _assert_no_forbidden_loading_ui(page, label)
    url_page = _url_page_param(page)
    # First Dashboard admit may omit ?page= until an explicit navigate; accept either.
    url_ok = url_page == route or (route == "Dashboard" and url_page in {"", "Dashboard"})
    if not url_ok:
        raise AssertionError(
            f"{label}: URL page={url_page!r} does not match route={route!r} "
            f"(url={page.url!r})"
        )
    sync = _route_sync_probe(page, route)
    if sync.get("topbarLabel") != route:
        raise AssertionError(
            f"{label}: topbar label={sync.get('topbarLabel')!r} != {route!r}"
        )
    if not sync.get("selected"):
        raise AssertionError(
            f"{label}: sidebar item for {route!r} is not selected "
            f"(slug={ROUTE_NAV_SLUGS[route]!r})"
        )
    if not sync.get("contentOk"):
        raise AssertionError(
            f"{label}: main content markers missing for {route!r} "
            f"(preview={sync.get('textPreview')!r})"
        )
    if sync.get("hasStaleAf") or sync.get("hasStaleCompare") or sync.get("hasStaleQa"):
        raise AssertionError(
            f"{label}: stale prior-route content under {route!r} "
            f"(preview={sync.get('textPreview')!r})"
        )
    if sync.get("hasStaleDashboard"):
        raise AssertionError(
            f"{label}: Dashboard content under {route!r} chrome "
            f"(preview={sync.get('textPreview')!r})"
        )
    if sync.get("staleHit"):
        raise AssertionError(
            f"{label}: forbidden stale marker {sync.get('staleHit')!r} under {route!r} "
            f"(preview={sync.get('textPreview')!r})"
        )
    _assert_no_continuity_skeleton_above_content(page, label)


def _find_login_fields(page):
    for frame in [page, *page.frames]:
        email = frame.locator(
            'input[type="email"], input[autocomplete="email"], '
            'input[aria-label="Email"], div[data-testid="stTextInput"] input'
        ).first
        password = frame.locator(
            'input[type="password"], input[autocomplete="current-password"], '
            'div[data-testid="stTextInput"] input[type="password"]'
        ).first
        try:
            if email.count() and password.count():
                return frame, email, password
        except Exception:
            continue
    return None, None, None


def _click_foundation_nav(page, route: str) -> None:
    # Prefer session-safe foundation nav buttons; fall back to link text.
    candidates = [
        page.locator(f'.st-key-cv_foundation_navigation button:has-text("{route}")').first,
        page.locator(f'[class*="st-key-cv_foundation_navigation"] button:has-text("{route}")').first,
        page.locator(f'button:has-text("{route}")').first,
        page.locator(f'a.cv-foundation-nav-link:has-text("{route}")').first,
    ]
    last_exc: Exception | None = None
    for loc in candidates:
        try:
            if loc.count():
                loc.click(timeout=8000)
                return
        except Exception as exc:
            last_exc = exc
            continue
    raise AssertionError(f"foundation nav control for {route!r} not found ({last_exc})")


def _clear_smoke_session_cookie(page) -> None:
    """Expire the DI smoke cookie so logout cannot silently re-admit."""
    try:
        page.evaluate(
            """() => {
              document.cookie = "cadivor_auth_gate_smoke=; path=/; Max-Age=0; SameSite=Lax";
            }"""
        )
    except Exception:
        pass
    try:
        context = page.context
        stale = [
            c for c in context.cookies() if c.get("name") == "cadivor_auth_gate_smoke"
        ]
        if stale:
            # Prefer targeted clear when Playwright supports it; otherwise drop only
            # the smoke cookie by rewriting the jar without a full wipe mid-run.
            try:
                context.clear_cookies(name="cadivor_auth_gate_smoke")
            except TypeError:
                remaining = [
                    c
                    for c in context.cookies()
                    if c.get("name") != "cadivor_auth_gate_smoke"
                ]
                context.clear_cookies()
                if remaining:
                    context.add_cookies(remaining)
    except Exception:
        pass


def _click_sign_out(page, *, app_url: str) -> None:
    """Open the foundation profile popover and click Sign out.

    Production logout clears the session then issues a same-tab location.replace.
    Headless Chromium can stall on that components.html reload, so after Sign out
    we wait briefly and, if the viewport stays blank, recover with an explicit
    navigation to the app URL (session already cleared). The DI smoke cookie is
    cleared explicitly so a recovery goto cannot auto-restore the session.
    """
    candidates = [
        page.locator('.st-key-cv_foundation_profile_menu button').first,
        page.locator('[class*="st-key-cv_foundation_profile_menu"] button').first,
    ]
    opened = False
    for loc in candidates:
        try:
            if loc.count():
                loc.click(timeout=8000)
                opened = True
                break
        except Exception:
            continue
    if not opened:
        raise AssertionError("profile menu button not found for logout")
    page.wait_for_timeout(500)
    signout = page.locator(
        'button:has-text("Sign out"), [class*="st-key-cv_foundation_signout"] button'
    ).first
    if not signout.count():
        raise AssertionError("Sign out control not found")
    signout.click(timeout=8000)

    # Prefer a natural reload/login paint; fall back to goto if blank stalls.
    for i in range(40):
        try:
            html = page.content()
            body = (page.inner_text("body") or "").strip()
        except Exception:
            html, body = "", ""
        target, _, _ = _find_login_fields(page)
        if target is not None and 'data-auth-gate="login"' in html:
            _clear_smoke_session_cookie(page)
            return
        probe = _viewport_probe(page) if body else {"blankCanvas": True}
        if (not body) or probe.get("blankCanvas") or i in {5, 12, 20}:
            _clear_smoke_session_cookie(page)
            if i in {5, 12, 20} or (not body) or probe.get("blankCanvas"):
                try:
                    page.goto(app_url, wait_until="domcontentloaded", timeout=90000)
                except Exception:
                    pass
        page.wait_for_timeout(400)
    # Final recovery attempt after clearing the DI smoke cookie.
    _clear_smoke_session_cookie(page)
    page.goto(app_url, wait_until="domcontentloaded", timeout=90000)
    page.wait_for_timeout(800)



def _wait_for_login_surface(page, label: str, *, frames_dir: Path, prefix: str) -> None:
    for i in range(60):
        _assert_no_visible_markup(page, f"{label}_{i}")
        body = page.inner_text("body") or ""
        if body.strip():
            _assert_visible_branded_surface(page, f"{label}_{i}")
        html = page.content()
        target, _, _ = _find_login_fields(page)
        if target is not None and 'data-auth-gate="login"' in html:
            page.screenshot(path=str(frames_dir / f"{prefix}_login.png"), full_page=True)
            (frames_dir / f"{prefix}_login.html").write_text(
                html[:200000], encoding="utf-8"
            )
            return
        if i in {0, 2, 5, 10, 20}:
            page.screenshot(
                path=str(frames_dir / f"{prefix}_t{i:02d}.png"), full_page=True
            )
        page.wait_for_timeout(400)
    raise AssertionError(f"{label}: Login surface never returned")


def _wait_for_route(page, route: str, label: str, *, frames_dir: Path, prefix: str) -> None:
    ready = False
    markers = ROUTE_CONTENT_MARKERS.get(route, (route,))
    last_detail = ""
    for i in range(120):
        _assert_no_visible_markup(page, f"{label}_{i}")
        _assert_visible_branded_surface(page, f"{label}_{i}")
        _assert_auth_surface_invariants(page, f"{label}_{i}")
        try:
            _assert_authenticated_continuity(page, f"{label}_{i}")
        except AssertionError:
            page.screenshot(
                path=str(frames_dir / f"{prefix}_continuity_fail_{i:02d}.png"),
                full_page=True,
            )
            (frames_dir / f"{prefix}_continuity_fail_{i:02d}.html").write_text(
                page.content()[:200000], encoding="utf-8"
            )
            raise
        try:
            _assert_in_flight_route_frame(page, route, f"{label}_inflight_{i}")
        except AssertionError as exc:
            page.screenshot(
                path=str(frames_dir / f"{prefix}_inflight_fail_{i:02d}.png"),
                full_page=True,
            )
            (frames_dir / f"{prefix}_inflight_fail_{i:02d}.html").write_text(
                page.content()[:200000], encoding="utf-8"
            )
            raise AssertionError(f"{label}: in-flight route frame failed: {exc}") from exc
        try:
            _assert_settled_route(page, route, f"{label}_settle_{i}")
            ready = True
            break
        except AssertionError as exc:
            last_detail = str(exc)
        if i in {0, 2, 5, 10, 20, 40}:
            page.screenshot(
                path=str(frames_dir / f"{prefix}_t{i:02d}.png"), full_page=True
            )
        page.wait_for_timeout(SAMPLE_MS)
    page.screenshot(path=str(frames_dir / f"{prefix}_final.png"), full_page=True)
    (frames_dir / f"{prefix}_final.html").write_text(
        page.content()[:200000], encoding="utf-8"
    )
    if not ready:
        raise AssertionError(
            f"{label}: route {route!r} never settled with matching chrome/content "
            f"(last={last_detail!r} markers={markers!r})"
        )


def _perform_valid_login(
    page,
    *,
    frames_dir: Path,
    prefix: str,
    expected_route: str = "Dashboard",
) -> None:
    target, email, password = _find_login_fields(page)
    if target is None:
        raise AssertionError(f"{prefix}: login fields missing")
    email.fill(MOCK_EMAIL)
    password.fill(MOCK_PASSWORD)
    target.locator(
        'button:has-text("Login"), button:has-text("Sign in"), button[type="submit"]'
    ).first.click(timeout=8000)

    saw_signing_in = False
    ready = False
    auth_surface_started_at = time.monotonic()
    for i in range(300):
        _assert_no_visible_markup(page, f"{prefix}_handoff_{i}")
        _assert_login_handoff_frame(
            page,
            f"{prefix}_handoff_{i}",
            auth_surface_started_at=auth_surface_started_at,
        )
        probe = _viewport_probe(page)
        if (
            probe.get("signingIn")
            or probe.get("cardSigningIn")
            or (
                probe.get("visibleGate")
                and probe.get("gateKind") == "authenticating"
            )
        ):
            if not saw_signing_in:
                page.screenshot(
                    path=str(frames_dir / f"{prefix}_signing_in.png"), full_page=True
                )
                (frames_dir / f"{prefix}_signing_in.html").write_text(
                    page.content()[:200000], encoding="utf-8"
                )
                page.screenshot(
                    path=str(frames_dir / f"{prefix}_login_submit.png"), full_page=True
                )
            saw_signing_in = True
            auth_surface_started_at = time.monotonic()
        # Capture immediate post-click frames even before probe catches copy.
        if i in {0, 1, 2, 3, 5, 10, 20, 40}:
            page.screenshot(
                path=str(frames_dir / f"{prefix}_t{i:02d}.png"), full_page=True
            )
            (frames_dir / f"{prefix}_t{i:02d}.html").write_text(
                page.content()[:200000], encoding="utf-8"
            )
            if i == 0:
                page.screenshot(
                    path=str(frames_dir / f"{prefix}_login_submit_t00.png"),
                    full_page=True,
                )
        if (
            probe.get("hasShell")
            and probe.get("pageContentReady")
            and not probe.get("signingIn")
        ):
            _assert_authenticated_continuity(page, f"{prefix}_shell_{i}")
            ready = True
            break
        page.wait_for_timeout(SAMPLE_MS)
    if not saw_signing_in:
        raise AssertionError(f"{prefix}: never observed Signing you in… during handoff")
    if not ready:
        raise AssertionError(f"{prefix}: stuck before authenticated shell+content")
    _wait_for_route(
        page,
        expected_route,
        label=f"{prefix}_{expected_route.lower().replace(' ', '_')}",
        frames_dir=frames_dir,
        prefix=f"{prefix}_{expected_route.lower().replace(' ', '_')}",
    )


def main() -> int:
    OUT.mkdir(parents=True, exist_ok=True)
    reuse_url = str(os.environ.get("CADIVOR_AUTH_SMOKE_URL") or "").strip()
    proc = None
    log_path = OUT / "streamlit_harness.log"
    url = reuse_url or f"http://127.0.0.1:{PORT}"

    if not reuse_url:
        # Never attach to a stale Streamlit from a prior smoke run.
        try:
            import signal as _signal
            import subprocess as _sp

            listed = _sp.check_output(
                ["lsof", "-tiTCP:%d" % PORT, "-sTCP:LISTEN"],
                text=True,
            ).strip()
            for pid_s in listed.split():
                try:
                    os.kill(int(pid_s), _signal.SIGTERM)
                except Exception:
                    pass
            time.sleep(0.6)
        except Exception:
            pass
        env = os.environ.copy()
        # Provider-boundary doubles via test-only PYTHONPATH sitecustomize only.
        # Never set a production mock-auth env switch.
        env.pop("CADIVOR_AUTH_GATE_MOCK", None)
        env.pop("CADIVOR_AUTH_SMOKE", None)
        existing_pythonpath = str(env.get("PYTHONPATH") or "").strip()
        env["PYTHONPATH"] = (
            SMOKE_PYTHONPATH
            if not existing_pythonpath
            else f"{SMOKE_PYTHONPATH}{os.pathsep}{existing_pythonpath}"
        )
        env.setdefault("SUPABASE_URL", "https://example.supabase.co")
        env.setdefault("SUPABASE_ANON_KEY", "public-anon-key-for-smoke")
        env.setdefault("SUPABASE_KEY", "public-anon-key-for-smoke")
        log_fh = open(log_path, "w", encoding="utf-8")
        proc = subprocess.Popen(
            [
                STREAMLIT_PY,
                "-m",
                "streamlit",
                "run",
                SMOKE_APP,
                "--server.port",
                str(PORT),
                "--server.address",
                "127.0.0.1",
                "--server.headless",
                "true",
                "--server.fileWatcherType",
                "none",
                "--browser.serverAddress",
                "127.0.0.1",
                "--browser.serverPort",
                str(PORT),
                "--browser.gatherUsageStats",
                "false",
            ],
            cwd=str(ROOT),
            env=env,
            stdout=log_fh,
            stderr=subprocess.STDOUT,
        )
        import urllib.request

        for _ in range(90):
            try:
                urllib.request.urlopen(url, timeout=1)
                break
            except Exception:
                time.sleep(0.5)
        else:
            print("AUTH_SMOKE fail=server_start")
            return 2

    try:
        from playwright.sync_api import sync_playwright
    except Exception as exc:
        print(f"AUTH_SMOKE fail=playwright_import detail={exc}")
        return 3

    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            page = browser.new_page(viewport={"width": 1280, "height": 900})
            page.goto(url, wait_until="domcontentloaded", timeout=90000)

            # 1) Cold signed-out load → Login visible directly.
            saw_restoring_before_login = False
            for _ in range(40):
                html = page.content()
                body = page.inner_text("body") or ""
                if body.strip():
                    _assert_no_visible_markup(page, "cold_start_wait")
                    _assert_visible_branded_surface(page, "cold_start_wait")
                if "Restoring your session" in body:
                    saw_restoring_before_login = True
                target, email, password = _find_login_fields(page)
                if target is not None and 'data-auth-gate="login"' in html:
                    break
                page.wait_for_timeout(500)
            else:
                page.screenshot(path=str(OUT / "01_boot_or_login.png"), full_page=True)
                (OUT / "01_boot_or_login.html").write_text(
                    page.content()[:200000], encoding="utf-8"
                )
                print("AUTH_SMOKE fail=no_login_inputs")
                return 4

            if saw_restoring_before_login:
                raise AssertionError(
                    "cold_start: intermediate boot surface shown before Login"
                )

            page.screenshot(path=str(OUT / "01_cold_login.png"), full_page=True)
            page.screenshot(path=str(OUT / "01_boot_or_login.png"), full_page=True)
            html = page.content()
            _assert_not_blank_topbar(html, "cold_login")
            _assert_no_visible_markup(page, "cold_login")
            _assert_visible_branded_surface(page, "cold_login")
            (OUT / "01_cold_login.html").write_text(html[:200000], encoding="utf-8")
            (OUT / "01_boot_or_login.html").write_text(html[:200000], encoding="utf-8")
            assert 'data-auth-gate="login"' in html
            login_body = page.inner_text("body") or ""
            if "Restoring your session" in login_body:
                raise AssertionError("login: boot restore message still visible")

            # 2) Invalid login → Login remains usable with error.
            email.fill("wrong@cadivor.test")
            password.fill("not-the-password")
            target.locator(
                'button:has-text("Login"), button:has-text("Sign in"), button[type="submit"]'
            ).first.click(timeout=8000)
            page.wait_for_timeout(2500)
            page.screenshot(path=str(OUT / "02_invalid_password.png"), full_page=True)
            html_bad = page.content()
            body_bad = page.inner_text("body") or ""
            _assert_not_blank_topbar(html_bad, "invalid_password")
            _assert_no_visible_markup(page, "invalid_login")
            _assert_visible_branded_surface(page, "invalid_login")
            (OUT / "02_invalid_password.html").write_text(
                html_bad[:200000], encoding="utf-8"
            )
            if "incorrect" not in body_bad.casefold():
                raise AssertionError("invalid_login: expected error copy missing")
            target, email, password = _find_login_fields(page)
            if target is None:
                print("AUTH_SMOKE fail=login_fields_after_invalid")
                return 5
            if 'data-auth-gate="login"' not in html_bad:
                raise AssertionError("invalid_login: Login gate not still usable")

            # 3) Valid login → continuous Signing you in… → Dashboard.
            try:
                _perform_valid_login(page, frames_dir=OUT, prefix="03_first_login")
            except AssertionError as exc:
                print(f"AUTH_SMOKE fail=first_login detail={exc}")
                return 6
            page.screenshot(path=str(OUT / "04_dashboard_ready.png"), full_page=True)
            (OUT / "04_dashboard_ready.html").write_text(
                page.content()[:200000], encoding="utf-8"
            )
            if "Mock workspace ready" in page.content() or "cadivor-auth-ready" in page.content():
                raise AssertionError(
                    "ready: synthetic smoke ready surface still in use — "
                    "must exercise real authenticated_runtime / unified_shell"
                )
            try:
                _assert_first_login_matches_reload_dashboard_geometry(
                    page, frames_dir=OUT, tolerance_px=4.0
                )
            except AssertionError as exc:
                print(f"AUTH_SMOKE fail=first_login_layout detail={exc}")
                return 6

            # 3b) Logout, then deep-link login with ?page=BOM Analyzer.
            try:
                _click_sign_out(page, app_url=url)
                _wait_for_login_surface(
                    page, "before_deeplink", frames_dir=OUT, prefix="05_before_deeplink"
                )
            except AssertionError as exc:
                print(f"AUTH_SMOKE fail=deeplink_prep detail={exc}")
                return 7
            deeplink_url = f"{url}?page=BOM%20Analyzer"
            page.goto(deeplink_url, wait_until="domcontentloaded", timeout=90000)
            for _ in range(60):
                html = page.content()
                target, _, _ = _find_login_fields(page)
                if target is not None and 'data-auth-gate="login"' in html:
                    break
                page.wait_for_timeout(SAMPLE_MS)
            else:
                print("AUTH_SMOKE fail=deeplink_login_missing")
                return 7
            try:
                _perform_valid_login(
                    page,
                    frames_dir=OUT,
                    prefix="06_deeplink_bom",
                    expected_route="BOM Analyzer",
                )
            except AssertionError as exc:
                print(f"AUTH_SMOKE fail=deeplink_login detail={exc}")
                return 7
            page.screenshot(path=str(OUT / "06_deeplink_bom_final.png"), full_page=True)
            # Return to Dashboard before the standard nav circuit.
            _click_foundation_nav(page, "Dashboard")
            _wait_for_route(
                page,
                "Dashboard",
                label="deeplink_return_dashboard",
                frames_dir=OUT,
                prefix="06_deeplink_return_dashboard",
            )

            # 4) Authenticated route circuit with four-way settled assertions.
            route_prefixes = {
                "Dashboard": "07_dashboard",
                "BOM Analyzer": "08_bom_analyzer",
                "Compare Parts": "09_compare_parts",
                "Alternative Finder": "10_alternative_finder",
                "Datasheet Q&A": "11_datasheet_qa",
                "Procurement Advisor": "12_procurement_advisor",
            }
            # First Dashboard already settled; continue BOM → Compare → … → Dashboard.
            for idx, route in enumerate(AUTH_ROUTE_CIRCUIT):
                if idx == 0:
                    # Already on Dashboard after login.
                    _assert_settled_route(page, "Dashboard", "circuit_start_dashboard")
                    page.screenshot(
                        path=str(OUT / "07_dashboard_final.png"), full_page=True
                    )
                    continue
                _click_foundation_nav(page, route)
                prefix = route_prefixes[route]
                if idx == len(AUTH_ROUTE_CIRCUIT) - 1:
                    prefix = "13_dashboard_return"
                try:
                    _wait_for_route(
                        page,
                        route,
                        label=f"nav_{route}_{idx}",
                        frames_dir=OUT,
                        prefix=prefix,
                    )
                except AssertionError as exc:
                    print(f"AUTH_SMOKE fail=route_layout route={route} detail={exc}")
                    return 8

            # 5) Logout → Login → valid login again.
            try:
                _click_sign_out(page, app_url=url)
            except AssertionError as exc:
                print(f"AUTH_SMOKE fail=logout_click detail={exc}")
                return 9
            try:
                _wait_for_login_surface(
                    page, "after_logout", frames_dir=OUT, prefix="14_logout"
                )
            except AssertionError as exc:
                print(f"AUTH_SMOKE fail=logout_login_surface detail={exc}")
                return 9
            # Logout→Login must not leave a blank frame as the settled surface.
            _assert_visible_branded_surface(page, "after_logout_settled")
            probe_logout = _viewport_probe(page)
            if not probe_logout.get("hasLogin"):
                raise AssertionError("after_logout: Login gate not visible")
            page.screenshot(path=str(OUT / "14_logout_login.png"), full_page=True)

            try:
                _perform_valid_login(page, frames_dir=OUT, prefix="15_relogin")
            except AssertionError as exc:
                print(f"AUTH_SMOKE fail=relogin detail={exc}")
                return 10
            page.screenshot(path=str(OUT / "15_relogin_dashboard.png"), full_page=True)
            (OUT / "15_relogin_dashboard.html").write_text(
                page.content()[:200000], encoding="utf-8"
            )

            browser.close()
        print(f"AUTH_SMOKE ok screenshots={OUT}")
        return 0
    finally:
        if proc is not None:
            proc.send_signal(signal.SIGTERM)
            try:
                proc.wait(timeout=8)
            except Exception:
                proc.kill()


if __name__ == "__main__":
    raise SystemExit(main())
