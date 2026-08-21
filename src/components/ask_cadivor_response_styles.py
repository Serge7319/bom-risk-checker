"""Sprint 72.3.6+ — Static inline presentation styles for Ask Cadivor response surfaces.

Literal colors and widely supported CSS only. These styles must not depend on the
external ask_cadivor_v2.css contract. Never interpolate dynamic content here.

Sprint 72.3.7 polish: spacing rhythm, section separation, reason/action hierarchy.
"""

from __future__ import annotations

# Conversation exchange (cv50)
CV50_EXCHANGE_STYLE = (
    "display:grid;gap:12px;margin:12px 0 16px;padding:16px;"
    "border:1px solid #e2e8f0;border-radius:16px;background:#f8fafc;"
)
CV50_EXCHANGE_TOP_STYLE = (
    "display:flex;align-items:flex-start;justify-content:space-between;"
    "gap:16px;flex-wrap:wrap;min-width:0;"
)
CV50_YOU_ASKED_STYLE = "display:grid;gap:6px;min-width:0;flex:1 1 auto;"
CV50_YOU_ASKED_LABEL_STYLE = (
    "display:block;font-size:11px;font-weight:700;letter-spacing:0.08em;"
    "text-transform:uppercase;color:#64748b;"
)
CV50_YOU_ASKED_QUESTION_STYLE = (
    "display:block;font-size:13px;font-weight:500;color:#475569;"
    "line-height:1.55;max-width:62ch;min-width:0;"
)
CV50_EXCHANGE_BADGES_STYLE = (
    "display:flex;flex-wrap:wrap;align-items:center;justify-content:flex-end;"
    "gap:8px;flex:0 0 auto;"
)
CV50_TYPE_BADGE_STYLE = (
    "display:inline-flex;align-items:center;min-height:26px;border-radius:999px;"
    "padding:5px 10px;font-size:10px;font-weight:700;white-space:nowrap;"
    "border:1px solid #e2e8f0;background:#ffffff;color:#2563eb;"
)
CV50_SAVED_BADGE_STYLE = (
    "display:inline-flex;align-items:center;min-height:26px;border-radius:999px;"
    "padding:5px 10px;font-size:10px;font-weight:700;white-space:nowrap;"
    "border:1px solid #d1fae5;background:#ecfdf5;color:#047857;"
)

# Answer card (cv49/cv722)
CV49_ANSWER_CARD_STYLE = (
    "display:grid;gap:16px;border:1px solid #e2e8f0;border-radius:20px;"
    "background:#ffffff;padding:18px 20px;margin:12px 0;max-width:920px;min-width:0;"
)
CV49_ANSWER_KICKER_STYLE = (
    "display:block;font-size:11px;font-weight:700;letter-spacing:0.08em;"
    "text-transform:uppercase;color:#2563eb;margin-bottom:8px;"
)
CV722_DIRECT_ANSWER_STYLE = "display:grid;gap:8px;min-width:0;"
CV722_SECTION_LABEL_STYLE = (
    "display:block;font-size:11px;font-weight:700;letter-spacing:0.06em;"
    "text-transform:uppercase;color:#64748b;margin:0 0 4px;"
)
CV722_DIRECT_ANSWER_TITLE_STYLE = (
    "display:block;font-size:20px;font-weight:700;color:#0f172a;line-height:1.3;"
)
CV722_DIRECT_ANSWER_TEXT_STYLE = (
    "display:block;margin:0;font-size:15px;color:#0f172a;line-height:1.62;max-width:72ch;"
)
CV722_CONCISE_BLOCK_STYLE = "display:grid;gap:8px;min-width:0;"
CV722_LIST_STYLE = (
    "margin:0;padding:0;list-style:none;display:grid;gap:10px;min-width:0;"
)

# Reason / action rows
CV722_REASON_ROW_STYLE = (
    "display:grid;grid-template-columns:36px minmax(0,1fr);gap:12px;"
    "align-items:center;padding:10px 12px;border-radius:12px;list-style:none;"
    "background:#fafbfc;border:1px solid #e8edf2;min-width:0;"
)
CV722_ACTION_ROW_STYLE = (
    "display:grid;grid-template-columns:36px minmax(0,1fr);gap:12px;"
    "align-items:center;padding:10px 12px;border-radius:12px;list-style:none;"
    "background:#f0f7ff;border:1px solid #bfdbfe;min-width:0;"
)
CV722_REASON_INDEX_STYLE = (
    "display:grid;place-items:center;width:28px;height:28px;border-radius:8px;"
    "font-size:11px;font-weight:800;background:#eff6ff;color:#2563eb;flex-shrink:0;"
)
CV722_ACTION_INDEX_STYLE = (
    "display:grid;place-items:center;width:28px;height:28px;border-radius:8px;"
    "font-size:11px;font-weight:800;background:#2563eb;color:#ffffff;flex-shrink:0;"
)
CV722_ROW_BODY_STYLE = "min-width:0;"
CV722_ROW_BODY_TEXT_STYLE = (
    "display:block;margin:0;font-size:13px;line-height:1.6;color:#475569;"
    "word-break:break-word;"
)
CV722_ACTION_BODY_TEXT_STYLE = (
    "display:block;margin:0;font-size:13px;line-height:1.6;color:#0f172a;font-weight:500;"
    "word-break:break-word;"
)

# Decision summary
CV722_SUMMARY_STRIP_STYLE = (
    "display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:12px;"
    "margin:16px 0;padding:12px 16px;border:1px solid #e2e8f0;border-radius:16px;"
    "background:linear-gradient(180deg,#f8fafc 0%,#ffffff 100%);max-width:920px;min-width:0;"
)
CV722_SUMMARY_ITEM_STYLE = "display:grid;gap:6px;min-width:0;"
CV722_SUMMARY_LABEL_STYLE = CV722_SECTION_LABEL_STYLE
CV722_SUMMARY_VALUE_STYLE = (
    "display:block;font-size:15px;font-weight:700;color:#0f172a;line-height:1.3;word-break:break-word;"
)
CV722_SUMMARY_VALUE_STATUS_STYLE = CV722_SUMMARY_VALUE_STYLE + "color:#b45309;"
CV722_SUMMARY_VALUE_PRIORITY_STYLE = (
    "display:block;font-size:18px;font-weight:700;color:#2563eb;line-height:1.3;word-break:break-word;"
)
CV722_SUMMARY_NOTE_STYLE = (
    "display:block;font-size:10px;color:#64748b;line-height:1.45;margin:0;"
)

# Assessment shell
CV727_ASSESSMENT_PANEL_STYLE = (
    "display:grid;gap:12px;border:1px solid #e2e8f0;border-radius:16px;"
    "background:linear-gradient(180deg,#f8fafc 0%,#ffffff 100%);padding:12px 16px;min-width:0;"
)
CV727_ASSESSMENT_HEADING_STYLE = (
    "display:block;margin:0;font-size:11px;font-weight:700;letter-spacing:0.08em;"
    "text-transform:uppercase;color:#2563eb;"
)
CV727_ASSESSMENT_BODY_STYLE = "display:grid;gap:16px;min-width:0;"
CV727_SECTION_SEPARATOR_STYLE = (
    "display:block;height:0;margin:0;border:0;border-top:1px solid #eef2f6;"
)
CV35_SECTION_LABEL_STYLE = (
    "display:block;font-size:11px;font-weight:700;letter-spacing:0.08em;"
    "text-transform:uppercase;color:#2563eb;margin:0 0 8px;"
)

# Impact / confidence grids
CV724_IMPACT_GRID_STYLE = (
    "display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:8px;"
    "margin:8px 0 12px;min-width:0;"
)
CV724_DRIVER_GRID_STYLE = CV724_IMPACT_GRID_STYLE
CV724_METRIC_CELL_STYLE = (
    "display:grid;gap:6px;padding:10px 12px;border:1px solid #e2e8f0;border-radius:12px;"
    "background:#f8fafc;min-width:0;"
)
CV39_IMPACT_LABEL_STYLE = CV722_SECTION_LABEL_STYLE
CV39_IMPACT_VALUE_STYLE = CV722_SUMMARY_VALUE_STYLE
CV39_IMPACT_NOTE_STYLE = CV722_SUMMARY_NOTE_STYLE
CV46_DRIVER_LABEL_STYLE = CV722_SECTION_LABEL_STYLE
CV46_DRIVER_VALUE_STYLE = CV722_SUMMARY_VALUE_STYLE
CV46_DRIVER_NOTE_STYLE = CV722_SUMMARY_NOTE_STYLE
CV724_IMPACT_DISCLAIMER_STYLE = (
    "display:block;margin:0 0 16px;font-size:11px;line-height:1.5;color:#64748b;max-width:72ch;"
)

# Evidence breakdown
CV46_EVIDENCE_BOARD_STYLE = (
    "display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:8px;"
    "margin:8px 0 16px;min-width:0;"
)
CV46_EVIDENCE_CARD_STYLE = (
    "display:grid;gap:12px;border:1px solid #e2e8f0;border-radius:16px;"
    "background:#ffffff;padding:16px;min-width:0;"
)
CV46_EVIDENCE_HEADER_STYLE = (
    "display:flex;align-items:center;justify-content:space-between;gap:8px;min-width:0;"
)
CV46_EVIDENCE_COMPONENT_STYLE = (
    "display:block;font-size:14px;font-weight:800;color:#0f172a;min-width:0;flex:1 1 auto;"
)
CV46_EVIDENCE_STATUS_STYLE = (
    "display:inline-flex;align-items:center;flex-shrink:0;padding:2px 8px;"
    "border-radius:999px;font-size:11px;font-weight:700;letter-spacing:0.06em;"
    "text-transform:uppercase;color:#64748b;background:#f8fafc;border:1px solid #e2e8f0;"
)
CV46_EVIDENCE_BODY_STYLE = "display:grid;gap:4px;min-width:0;"
CV46_EVIDENCE_LABEL_STYLE = CV722_SECTION_LABEL_STYLE
CV46_EVIDENCE_STATEMENT_STYLE = (
    "display:block;margin:0;font-size:13px;line-height:1.58;color:#475569;"
    "word-break:break-word;"
)
