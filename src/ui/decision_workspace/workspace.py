"""Sprint 69 recommendation workspace renderer."""
from __future__ import annotations

from typing import Any, Mapping, Sequence

import streamlit.components.v1 as components

from src.ui.decision_workspace._utils import INSUFFICIENT_EVIDENCE, esc
from src.ui.decision_workspace.components import (
    recommendation_card,
    recommendation_details,
    recommendation_summary,
)


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
        f'<template id="cv69-detail-template-{index}">{recommendation_details(action)}</template>'
        for index, action in enumerate(rows)
    )

    return f"""
    <div class="cv69-action-workspace">
      {recommendation_summary(rows, report=report, brief=brief)}
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
        if (!root || root.dataset.cv69Bound === '1') return;
        root.dataset.cv69Bound = '1';

        const cards = Array.from(root.querySelectorAll('.cv69-recommendation-card'));
        const detailPanel = root.querySelector('.cv69-rec-detail-content');
        const detailEmpty = root.querySelector('.cv69-rec-detail-empty');
        const detailHost = root.querySelector('.cv69-rec-detail');
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
          const index = card.getAttribute('data-cv69-index');
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

        cards.forEach((card) => {
          if (card.dataset.cv69Bound === '1') return;
          card.dataset.cv69Bound = '1';
          card.addEventListener('click', () => selectCard(card, true));
        });

        if (cards.length) {
          selectCard(cards[0], false);
        }
      };

      doc.querySelectorAll('.cv69-action-workspace').forEach(bindWorkspace);
    })();
    </script>
    """


def render_recommendation_workspace(
    actions: Sequence[Mapping[str, Any]],
    brief: Mapping[str, Any],
) -> None:
    import streamlit as st

    st.html(render_recommendation_workspace_html(actions, brief))
    components.html(recommendation_workspace_init_script(), height=0)
