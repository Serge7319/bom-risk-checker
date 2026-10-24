"""Sprint 69/70 recommendation workspace renderer."""
from __future__ import annotations

from typing import Any, Mapping, Sequence

from src.ui.decision_workspace._utils import INSUFFICIENT_EVIDENCE, esc
from src.ui.decision_workspace.components import (
    recommendation_card,
    recommendation_details,
    recommendation_summary,
)
from src.ui.decision_workspace.workflow_components import comparison_view, workspace_toolbar


def render_recommendation_workspace_html(
    actions: Sequence[Mapping[str, Any]],
    brief: Mapping[str, Any],
) -> str:
    rows = list(actions or [])
    if not rows:
        return f'<p class="cv671-muted">{esc(INSUFFICIENT_EVIDENCE)}</p>'

    report = brief.get("engineering_dependency_report") or {}
    list_cards = "".join(recommendation_card(action, index=index) for index, action in enumerate(rows))
    templates = "".join(
        f'<template id="cv69-detail-template-{index}">'
        f"{recommendation_details(action, index=index, brief=brief)}"
        f"</template>"
        for index, action in enumerate(rows)
    )

    return f"""
    <div class="cv69-action-workspace cv70-decision-workspace">
      {recommendation_summary(rows, report=report, brief=brief)}
      {workspace_toolbar()}
      {comparison_view(rows)}
      <div class="cv69-workspace-body">
        <aside class="cv69-rec-list" aria-label="Recommendation list">
          <div class="cv69-rec-list-inner">
            {list_cards}
          </div>
        </aside>
        <div class="cv69-rec-detail" id="cv69-detail-panel">
          <div class="cv69-rec-detail-empty">
            <span>Select a recommendation</span>
            <p>Choose an engineering action to review analysis, trade-offs, and timeline.</p>
          </div>
          <div class="cv69-rec-detail-content" hidden></div>
        </div>
      </div>
      {templates}
    </div>
    """


def recommendation_workspace_init_script() -> str:
    return """
    <script>
    (function () {
      const win = window.parent;
      const doc = win.document;

      const bindWorkspace = (root) => {
        if (!root || root.dataset.cv70Bound === '1') return;
        root.dataset.cv70Bound = '1';

        const cards = Array.from(root.querySelectorAll('.cv69-recommendation-card'));
        const detailPanel = root.querySelector('.cv69-rec-detail-content');
        const detailEmpty = root.querySelector('.cv69-rec-detail-empty');
        const detailHost = root.querySelector('.cv69-rec-detail');
        const compareRoot = root.querySelector('[data-cv70-comparison-root]');
        const compareDataEl = root.querySelector('[data-cv70-comparison-data]');
        const compareData = compareDataEl ? JSON.parse(compareDataEl.textContent || '[]') : [];

        const loadDetail = (index) => {
          if (!detailPanel) return;
          detailPanel.innerHTML = '';
          const template = doc.getElementById('cv69-detail-template-' + index);
          if (template) {
            detailPanel.appendChild(template.content.cloneNode(true));
          }
          detailPanel.dataset.cv69Active = String(index);
        };

        const selectCard = (card, scroll) => {
          const index = card.getAttribute('data-cv70-index');
          cards.forEach((other) => {
            const active = other === card;
            other.classList.toggle('is-selected', active);
            other.setAttribute('aria-selected', active ? 'true' : 'false');
          });
          if (detailEmpty) detailEmpty.hidden = true;
          if (detailPanel) detailPanel.hidden = false;
          loadDetail(index);
          if (scroll && detailHost) {
            const top = detailHost.getBoundingClientRect().top + win.scrollY - 88;
            win.scrollTo({ top: Math.max(0, top), behavior: 'smooth' });
          }
        };

        const applyFilter = (key) => {
          cards.forEach((card) => {
            let visible = true;
            const confidence = Number(card.getAttribute('data-confidence') || 0);
            const roi = Number(card.getAttribute('data-roi') || 0);
            const effort = Number(card.getAttribute('data-effort') || 0);
            if (key === 'high-confidence') visible = confidence >= 80;
            else if (key === 'highest-roi') visible = roi >= 1;
            else if (key === 'quick-wins') visible = card.getAttribute('data-quick-win') === '1';
            else if (key === 'production-blockers') visible = card.getAttribute('data-production-blocker') === '1';
            else if (key === 'low-effort') visible = effort <= 3;
            else if (key === 'awaiting-review') visible = card.getAttribute('data-awaiting-review') === '1';
            card.hidden = !visible;
          });
        };

        const applyView = (mode) => {
          root.classList.toggle('cv70-view-executive', mode === 'executive');
          root.classList.toggle('cv70-view-engineering', mode === 'engineering');
          if (detailPanel) {
            detailPanel.querySelectorAll('.cv70-decision-shell').forEach((shell) => {
              shell.classList.toggle('cv70-view-executive', mode === 'executive');
              shell.classList.toggle('cv70-view-engineering', mode === 'engineering');
            });
          }
        };

        const renderComparison = () => {
          if (!compareRoot) return;
          const selectA = compareRoot.querySelector('[data-cv70-compare-a]');
          const selectB = compareRoot.querySelector('[data-cv70-compare-b]');
          const grid = compareRoot.querySelector('[data-cv70-comparison-grid]');
          if (!selectA || !selectB || !grid) return;
          if (!selectA.options.length) {
            compareData.forEach((row) => {
              const label = row.part_number + ' — ' + row.title.slice(0, 42);
              selectA.add(new Option(label, row.index));
              selectB.add(new Option(label, row.index));
            });
            if (compareData.length > 1) selectB.selectedIndex = 1;
          }
          const a = compareData[Number(selectA.value)] || compareData[0];
          const b = compareData[Number(selectB.value)] || compareData[1] || compareData[0];
          const row = (label, left, right) =>
            '<div class="cv70-compare-row"><span>' + label + '</span><strong>' + left + '</strong><strong>' + right + '</strong></div>';
          grid.innerHTML =
            row('Confidence', a.confidence + '%', b.confidence + '%') +
            row('ROI score', a.roi, b.roi) +
            row('Health gain', '+' + a.health_gain, '+' + b.health_gain) +
            row('Effort (hrs)', a.effort, b.effort) +
            row('Validation', (a.validation || []).join(', '), (b.validation || []).join(', ')) +
            row('Trade-offs', (a.tradeoffs || []).join(' · '), (b.tradeoffs || []).join(' · ')) +
            row('Timeline', (a.timeline || []).join(' → '), (b.timeline || []).join(' → '));
        };

        cards.forEach((card) => {
          card.addEventListener('click', () => selectCard(card, true));
        });

        root.querySelectorAll('[data-cv70-filter]').forEach((btn) => {
          btn.addEventListener('click', () => {
            root.querySelectorAll('[data-cv70-filter]').forEach((b) => b.classList.remove('is-active'));
            btn.classList.add('is-active');
            applyFilter(btn.getAttribute('data-cv70-filter'));
          });
        });

        root.querySelectorAll('[data-cv70-view]').forEach((btn) => {
          btn.addEventListener('click', () => {
            root.querySelectorAll('[data-cv70-view]').forEach((b) => b.classList.remove('is-active'));
            btn.classList.add('is-active');
            applyView(btn.getAttribute('data-cv70-view'));
          });
        });

        const compareOpen = root.querySelector('[data-cv70-compare-open]');
        const compareClose = root.querySelector('[data-cv70-comparison-close]');
        if (compareOpen && compareRoot) {
          compareOpen.addEventListener('click', () => {
            compareRoot.hidden = false;
            renderComparison();
          });
        }
        if (compareClose && compareRoot) {
          compareClose.addEventListener('click', () => { compareRoot.hidden = true; });
        }
        compareRoot?.querySelectorAll('select').forEach((sel) => {
          sel.addEventListener('change', renderComparison);
        });

        if (cards.length) selectCard(cards.find((c) => !c.hidden) || cards[0], false);
      };

      doc.querySelectorAll('.cv70-decision-workspace').forEach(bindWorkspace);

      const deferBlocks = doc.querySelectorAll('.cv71-defer');
      if (deferBlocks.length && 'IntersectionObserver' in win) {
        const observer = new IntersectionObserver((entries) => {
          entries.forEach((entry) => {
            if (entry.isIntersecting) entry.target.classList.add('is-visible');
          });
        }, { root: null, threshold: 0.12 });
        deferBlocks.forEach((node) => observer.observe(node));
      } else {
        deferBlocks.forEach((node) => node.classList.add('is-visible'));
      }
    })();
    </script>
    """


def render_recommendation_workspace(
    actions: Sequence[Mapping[str, Any]],
    brief: Mapping[str, Any],
    *,
    record_context: Mapping[str, Any] | None = None,
) -> None:
    import streamlit as st
    import streamlit.components.v1 as components

    st.html(render_recommendation_workspace_html(actions, brief))
    components.html(recommendation_workspace_init_script(), height=0)
    if record_context:
        from src.ui.decision_workspace.records import render_recommendation_records

        render_recommendation_records(actions, **record_context)
