"""Candidate-row responsive layout for Find Replacement.

Drives the real `/find-replacement` page with a controlled API response.
Does not inject a hand-built table into the DOM.
"""
from __future__ import annotations

import json
import os
import re
import unittest
from pathlib import Path

from playwright.sync_api import sync_playwright


ROOT = Path(__file__).resolve().parents[1]
OUT = Path(
    os.environ.get("CADIVOR_REPLACEMENT_RESPONSIVE_OUT")
    or (ROOT / ".evidence_ui" / "replacement_table_responsive")
)
WEB = os.environ.get("CADIVOR_SMOKE_WEB", "http://127.0.0.1:3011").rstrip("/")
API = os.environ.get("CADIVOR_SMOKE_API", "http://127.0.0.1:8081").rstrip("/")
EMAIL = "sandbox-a@cadivor.test"
PASSWORD = "CadivorSandbox!a"

CONTROLLED_REPLACEMENT = {
    "requested_mpn": "AM29F010B-70EC",
    "original": {
        "mpn": "AM29F010B-70EC",
        "manufacturer": "AMD",
        "description": "1 Megabit CMOS Flash Memory",
        "lifecycle_status": "Obsolete",
    },
    "candidates": [
        {
            "mpn": "AM29F010B-90EC",
            "manufacturer": "AMD",
            "lifecycle_status": "Obsolete",
            "fit": (
                "not qualified — speed grade, temperature range, and package "
                "outline still require datasheet verification before any drop-in claim"
            ),
            "missing_evidence": [
                "manufacturer datasheet package outline",
                "speed grade timing table",
                "temperature range confirmation from identity-verified source",
            ],
            "rationale": "Same flash family catalog lead",
        }
    ],
    "unclassified_leads": [],
    "unfiltered_leads": [],
}

METRICS_JS = """() => {
  const shortLabels = new Set(["manufacturer", "lifecycle"]);
  const longLabels = new Set(["fit status", "evidence to verify"]);

  function contentClipped(el) {
    if (!el) return false;
    if (el.scrollWidth > el.clientWidth + 1) return true;
    return Array.from(el.children || []).some(
      (child) => child.scrollWidth > child.clientWidth + 1
    );
  }

  function valueColumnWidth(cell) {
    const style = window.getComputedStyle(cell);
    const box = cell.getBoundingClientRect();
    if (style.display === "grid") {
      return Math.max(0, box.width * 0.68);
    }
    const badge = cell.querySelector(".cv-badge");
    if (badge) return badge.getBoundingClientRect().width;
    return box.width;
  }

  const tables = Array.from(
    document.querySelectorAll(".cv-table-replacement--candidates")
  );
  return tables.map((table) => {
    const rows = Array.from(table.querySelectorAll("tbody tr")).slice(0, 8).map((row) => {
      const cells = Array.from(row.children);
      const rects = cells.map((cell) => {
        const box = cell.getBoundingClientRect();
        return {
          width: box.width,
          height: box.height,
          left: box.left,
          right: box.right,
          label: cell.getAttribute("data-label") || "",
          clipped: contentClipped(cell),
          valueWidth: Math.round(valueColumnWidth(cell)),
        };
      });
      const firstCell = cells[0];
      const stacked =
        window.getComputedStyle(row).display === "block" ||
        (firstCell &&
          ["block", "grid"].includes(window.getComputedStyle(firstCell).display));
      let overlap = false;
      if (!stacked) {
        for (let i = 1; i < rects.length; i += 1) {
          if (rects[i].left + 0.5 < rects[i - 1].right) overlap = true;
        }
      }
      const tall = !stacked && rects.some((rect) => rect.height > 280);
      const squeezed = !stacked && rects.some(
        (rect, idx) => idx < rects.length - 1 && rect.width > 0 && rect.width < 48
      );
      const clipped = rects.some((rect) => rect.clipped);
      const narrowStackedValue = stacked && rects.some((rect) => {
        const label = String(rect.label || "").toLowerCase();
        if (shortLabels.has(label)) return rect.valueWidth < 56;
        if (longLabels.has(label)) return rect.valueWidth < 96;
        return false;
      });
      return {
        overlap,
        tall,
        squeezed,
        clipped,
        narrowStackedValue,
        stacked,
        widths: rects.map((r) => Math.round(r.width)),
        valueWidths: rects.map((r) => r.valueWidth),
        labels: rects.map((r) => r.label),
      };
    });
    return {
      className: table.className,
      tableWidth: Math.round(table.getBoundingClientRect().width),
      rows,
    };
  });
}"""


def _servers_ready() -> bool:
    import urllib.error
    import urllib.request

    try:
        with urllib.request.urlopen(f"{WEB}/login", timeout=5) as resp:
            if resp.status >= 400:
                return False
        with urllib.request.urlopen(f"{API}/health", timeout=5) as resp:
            payload = json.loads(resp.read().decode())
            return bool(payload.get("ok"))
    except (urllib.error.URLError, TimeoutError, json.JSONDecodeError, ValueError):
        return False


@unittest.skipUnless(
    os.environ.get("CADIVOR_RUN_REPLACEMENT_RESPONSIVE") == "1" or _servers_ready(),
    "Local Next/API preview not running on CADIVOR_SMOKE_WEB/API",
)
class ReplacementTableResponsiveTests(unittest.TestCase):
    def test_candidate_row_at_1440_696_and_390(self):
        OUT.mkdir(parents=True, exist_ok=True)
        results = {"web": WEB, "api": API, "viewports": []}

        def fulfill(route):
            route.fulfill(
                status=200,
                content_type="application/json",
                body=json.dumps(CONTROLLED_REPLACEMENT),
            )

        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            context = browser.new_context(viewport={"width": 1440, "height": 1100})
            page = context.new_page()
            page.route("**/tools/find-replacement**", fulfill)

            page.goto(f"{WEB}/login", wait_until="networkidle")
            page.get_by_label("Email").fill(EMAIL)
            page.get_by_label("Password").fill(PASSWORD)
            page.get_by_role("button", name=re.compile(r"continue|sign in", re.I)).click()
            page.wait_for_function(
                "() => !window.location.pathname.includes('/login')",
                timeout=60000,
            )

            for width, height in ((1440, 1100), (696, 1188), (390, 844)):
                page.set_viewport_size({"width": width, "height": height})
                page.goto(f"{WEB}/find-replacement", wait_until="networkidle", timeout=60000)
                page.locator("#replacement-mpn").fill("AM29F010B-70EC")
                page.locator("#replacement-mfr").fill("AMD")
                page.get_by_role("button", name=re.compile(r"Find candidates", re.I)).click()
                page.wait_for_selector(
                    ".cv-table-replacement--candidates tbody tr",
                    timeout=30000,
                )
                page.wait_for_timeout(250)
                page.screenshot(
                    path=str(OUT / f"viewport_replacement_{width}.png"),
                    full_page=True,
                )
                # Prove the row came from the page component, not a hand-built prepend.
                injected = page.evaluate(
                    """() => Boolean(
                      document.querySelector(
                        '.cv-table-replacement--candidates[data-test-injected=\"1\"]'
                      )
                    )"""
                )
                self.assertFalse(injected)
                body_has_candidate = "AM29F010B-90EC" in page.locator("body").inner_text()
                self.assertTrue(body_has_candidate)
                metrics = page.evaluate(METRICS_JS)
                bad = [
                    row
                    for table in metrics
                    for row in table.get("rows") or []
                    if row.get("overlap")
                    or row.get("tall")
                    or row.get("squeezed")
                    or row.get("clipped")
                    or row.get("narrowStackedValue")
                ]
                results["viewports"].append(
                    {
                        "width": width,
                        "height": height,
                        "ok": bool(metrics) and not bad,
                        "bad_row_count": len(bad),
                        "tables": metrics,
                    }
                )
                self.assertTrue(metrics, f"no candidate table at {width}px")
                self.assertEqual(bad, [], msg=f"layout defects at {width}px: {bad}")

            browser.close()

        (OUT / "report.json").write_text(json.dumps(results, indent=2), encoding="utf-8")
        self.assertTrue(all(item["ok"] for item in results["viewports"]))


if __name__ == "__main__":
    unittest.main()
