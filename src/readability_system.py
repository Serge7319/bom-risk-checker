"""Shared readability CSS for Cadivor Milestone 15.1."""
def readability_css() -> str:
    return """
    <style id="cadivor-readability-15-1">
      html,body,[class*="css"]{font-size:16px}
      .stApp p,.stApp li,.stApp label{font-size:14px!important;line-height:1.55!important}
      [data-testid="stMetricLabel"] p{font-size:13px!important;font-weight:800!important;color:#52647a!important}
      [data-testid="stMetricValue"]{font-size:32px!important;font-weight:950!important;letter-spacing:-.035em!important}
      [data-testid="stMetric"]{padding:16px 17px!important;min-height:108px}
      .stTabs [data-baseweb="tab"]{font-size:13px!important;font-weight:850!important}
      .stButton button,.stDownloadButton button{font-size:13px!important;font-weight:850!important;min-height:42px!important}
      [data-testid="stCaptionContainer"] p{font-size:12px!important}
      .cv151-title{font-size:29px;font-weight:950;color:#0f172a;letter-spacing:-.04em;margin:0 0 8px}
      .cv151-subtitle{font-size:14px;font-weight:680;color:#52647a;line-height:1.55;max-width:940px}
      .cv151-hero{border:1px solid #bfdbfe;background:linear-gradient(135deg,#fff,#eef5ff);border-radius:24px;padding:24px;margin-bottom:16px;box-shadow:0 16px 42px rgba(37,99,235,.07)}
      .cv151-section-title{font-size:22px;font-weight:950;color:#0f172a;letter-spacing:-.025em;margin:22px 0 5px}
      .cv151-section-copy{font-size:13px;color:#64748b;font-weight:650;margin-bottom:12px}
      .cv151-card{border:1px solid #dbe3ef;background:#fff;border-radius:18px;padding:17px;margin-bottom:11px;box-shadow:0 10px 26px rgba(15,23,42,.045)}
      .cv151-card-title{font-size:16px;font-weight:950;color:#0f172a;line-height:1.3}
      .cv151-card-copy{font-size:13px;font-weight:680;color:#475569;line-height:1.52;margin-top:7px}
      .cv151-meta{display:flex;flex-wrap:wrap;gap:7px;margin-top:11px}.cv151-meta span{font-size:10px;font-weight:850;color:#1d4ed8;background:#eff6ff;border:1px solid #dbeafe;border-radius:999px;padding:6px 9px}
      .cv151-project{border:1px solid #e2e8f0;border-radius:17px;padding:16px;margin-bottom:10px;background:#fff}
      .cv151-progress{height:9px;background:#e2e8f0;border-radius:999px;overflow:hidden;margin:11px 0}.cv151-progress i{display:block;height:100%;background:#2563eb;border-radius:999px}
      .cv151-recommendation{border-left:4px solid #2563eb;background:#f8fbff;border-radius:0 14px 14px 0;padding:14px 16px;margin-bottom:10px;font-size:13px;font-weight:750;color:#334155;line-height:1.5}
      details summary{font-size:13px!important;font-weight:850!important}
    </style>
    """
