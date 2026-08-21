"""Shared readability and interaction system for Cadivor Milestone 16.0."""

def readability_css() -> str:
    return """
    <style id="cadivor-readability-16-0">
      html,body,[class*="css"]{font-size:16px}
      .stApp p,.stApp li,.stApp label{font-size:14px!important;line-height:1.58!important}

      [data-testid="stMetric"]{
        padding:18px 18px!important;
        min-height:112px;
        border-radius:16px;
      }
      [data-testid="stMetricLabel"] p{
        font-size:14px!important;
        font-weight:850!important;
        color:#52647a!important;
      }
      [data-testid="stMetricValue"]{
        font-size:34px!important;
        font-weight:950!important;
        letter-spacing:-.04em!important;
        color:#0f172a!important;
      }

      .stTabs [data-baseweb="tab"]{
        font-size:14px!important;
        font-weight:850!important;
        padding-left:14px!important;
        padding-right:14px!important;
      }
      .stButton button,.stDownloadButton button{
        font-size:14px!important;
        font-weight:650!important;
        min-height:46px!important;
        border-radius:10px!important;
      }
      [data-testid="stCaptionContainer"] p{font-size:12px!important}

      .cv151-title{
        font-size:31px;font-weight:950;color:#0f172a;
        letter-spacing:-.045em;margin:0 0 9px
      }
      .cv151-subtitle{
        font-size:15px;font-weight:680;color:#52647a;
        line-height:1.62;max-width:980px
      }
      .cv151-hero{
        border:1px solid #bfdbfe;
        background:linear-gradient(135deg,#fff,#eef5ff);
        border-radius:24px;padding:26px;margin-bottom:18px;
        box-shadow:0 16px 42px rgba(37,99,235,.07)
      }
      .cv151-section-title{
        font-size:24px;font-weight:950;color:#0f172a;
        letter-spacing:-.03em;margin:24px 0 5px
      }
      .cv151-section-copy{
        font-size:14px;color:#64748b;font-weight:650;margin-bottom:13px
      }
      .cv151-card,.cv151-project{
        border:1px solid #dbe3ef;background:#fff;border-radius:18px;
        padding:18px;margin-bottom:12px;
        box-shadow:0 10px 26px rgba(15,23,42,.045);
        transition:transform .16s ease,box-shadow .16s ease,border-color .16s ease
      }
      .cv151-card:hover,.cv151-project:hover{
        transform:translateY(-2px);
        border-color:#93c5fd;
        box-shadow:0 16px 34px rgba(37,99,235,.10)
      }
      .cv151-card-title{
        font-size:17px;font-weight:950;color:#0f172a;line-height:1.32
      }
      .cv151-card-copy{
        font-size:14px;font-weight:680;color:#475569;
        line-height:1.56;margin-top:8px
      }
      .cv151-meta{
        display:flex;flex-wrap:wrap;gap:8px;margin-top:12px
      }
      .cv151-meta span{
        font-size:11px;font-weight:850;color:#1d4ed8;
        background:#eff6ff;border:1px solid #dbeafe;
        border-radius:999px;padding:6px 10px
      }
      .cv151-progress{
        height:10px;background:#e2e8f0;border-radius:999px;
        overflow:hidden;margin:12px 0
      }
      .cv151-progress i{
        display:block;height:100%;background:#2563eb;border-radius:999px
      }
      .cv151-recommendation{
        border-left:4px solid #2563eb;background:#f8fbff;
        border-radius:0 14px 14px 0;padding:15px 17px;
        margin-bottom:10px;font-size:14px;font-weight:760;
        color:#334155;line-height:1.55
      }
      .cv160-priority-strip{
        display:grid;grid-template-columns:repeat(3,minmax(0,1fr));
        gap:12px;margin:14px 0 20px
      }
      .cv160-priority-box{
        border:1px solid #dbe3ef;background:#fff;border-radius:16px;
        padding:15px 16px
      }
      .cv160-priority-label{
        font-size:12px;font-weight:850;color:#64748b;margin-bottom:5px
      }
      .cv160-priority-value{
        font-size:26px;font-weight:950;color:#0f172a;letter-spacing:-.035em
      }
      .cv160-priority-box.today{
        border-color:#fecaca;background:#fff7f7
      }
      .cv160-priority-box.week{
        border-color:#fde68a;background:#fffcf3
      }
      .cv160-priority-box.later{
        border-color:#bfdbfe;background:#f8fbff
      }
      [data-testid="stDataFrame"] th,
      [data-testid="stDataFrame"] [role="columnheader"]{
        font-size:13px!important;font-weight:850!important;color:#334155!important
      }
      [data-testid="stDataFrame"] td,
      [data-testid="stDataFrame"] [role="gridcell"]{
        font-size:13px!important
      }
      .cv170-change-card{
        border:1px solid #bfdbfe;background:linear-gradient(135deg,#f8fbff,#fff);
        border-radius:18px;padding:18px 20px;margin:14px 0 20px
      }
      .cv170-change-title{font-size:18px;font-weight:950;color:#0f172a;margin-bottom:7px}
      .cv170-change-grid{display:grid;grid-template-columns:repeat(4,minmax(0,1fr));gap:10px;margin-top:12px}
      .cv170-change-item{background:#fff;border:1px solid #e2e8f0;border-radius:13px;padding:11px 12px}
      .cv170-change-value{font-size:22px;font-weight:950;color:#0f172a}
      .cv170-change-label{font-size:11px;font-weight:800;color:#64748b}
      .cv170-status-ready span{color:#047857!important;background:#ecfdf5!important;border-color:#a7f3d0!important}
      .cv170-status-review span{color:#a16207!important;background:#fffbeb!important;border-color:#fde68a!important}
      details summary{font-size:14px!important;font-weight:850!important}
      @media(max-width:900px){
        .cv160-priority-strip{grid-template-columns:1fr}
        [data-testid="stMetricValue"]{font-size:30px!important}
      }
    </style>
    """
