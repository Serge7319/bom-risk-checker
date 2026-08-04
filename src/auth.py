import streamlit as st
import streamlit.components.v1 as components
from datetime import datetime, timedelta
from textwrap import dedent

from src.auth_state import (
    APP_AUTHENTICATED, APP_LOGIN, APP_PUBLIC, APP_SIGNING_IN, APP_SIGNUP,
    mark_authenticated, render_auth_transition,
)
from src.config import CADIVOR_MARKETING_URL
from src.ui.core_premium_ui import inject_core_premium_ui_auth


def _set_auth_cookie(cookie_manager, session, key: str):
    """Compatibility no-op; auth persistence is session scoped."""
    return



CADIVOR_TERMS = """
### Cadivor Terms of Service

**Pre-launch version — Last updated July 25, 2026**

By creating an account, checking the acceptance box during registration, or using Cadivor, you agree to these Terms and the Privacy Policy.

#### 1. Decision-support service
Cadivor provides software-based component lifecycle, sourcing, supplier, inventory, risk, alternative-part, reporting, monitoring, and AI-assisted engineering intelligence for informational and decision-support purposes.

Cadivor does not replace professional engineering judgment, datasheet review, supplier confirmation, qualification testing, procurement review, regulatory review, manufacturing review, or production-release approval. You remain responsible for validating outputs before relying on them in a design, sourcing, procurement, compliance, manufacturing, or production workflow.

#### 2. Accounts and authorized use
You are responsible for maintaining accurate account information, protecting account credentials, and ensuring that people using your workspace are authorized to do so. You may not misuse the service, interfere with its operation, attempt unauthorized access, or use Cadivor for unlawful activity.

#### 3. Customer data and BOM ownership
You retain ownership of BOMs and other content you upload. You grant Cadivor permission to process that content only as reasonably necessary to provide analysis, reporting, monitoring, account administration, support, security, service reliability, and product operation.

You must not upload unlawful data or confidential third-party, export-controlled, restricted, regulated, or highly sensitive information unless you have the legal right and appropriate authorization to process it through the service.

#### 4. Supplier data and recommendations
Cadivor may use distributor APIs, supplier records, public sources, third-party data, software rules, and AI-assisted analysis. Availability, lifecycle status, pricing, stock, lead times, risk scores, compatibility assessments, and alternative recommendations may be incomplete, delayed, inaccurate, or unsuitable for a particular design.

You are responsible for confirming component specifications, fit, form, function, regulatory status, sourcing terms, and supplier information before purchasing, qualifying, or releasing a component.

#### 5. Plans, trials, billing, and changes
Plan features and usage limits are described on the Pricing page and may vary by subscription. Trial access may automatically continue on the Starter plan unless the customer upgrades or cancels as described during registration. Paid subscriptions, renewal, taxes, refunds, and cancellation terms will be presented during checkout and in the final commercial agreement.

#### 6. Availability and service changes
Cadivor may modify features, integrations, limits, or availability to improve the service, address security or legal requirements, or respond to third-party service changes. We will use reasonable efforts to communicate material changes that affect paid customers.

#### 7. Suspension and termination
Cadivor may suspend or terminate access for abuse, misuse, nonpayment, security risk, violation of these Terms, or activity that may harm the service or other users. Customers may stop using the service and cancel eligible subscriptions through the available account or billing process.

#### 8. Disclaimers
To the extent permitted by law, Cadivor is provided “as is” and “as available.” Cadivor does not warrant uninterrupted availability, complete accuracy, merchantability, non-infringement, or fitness for a particular purpose.

#### 9. Limitation of liability
To the maximum extent permitted by law, Cadivor and its owners, officers, employees, contractors, suppliers, service providers, and affiliates will not be liable for indirect, incidental, consequential, special, punitive, procurement, production, recall, lost-profit, lost-data, business-interruption, design-failure, regulatory, or manufacturing damages arising from use of the service.

#### 10. Contact
Questions about these Terms may be sent to **info@cadivor.com** with “Terms” in the subject line.

*This pre-launch version requires review by qualified counsel and completion with Cadivor’s legal entity name, business address, governing law, payment and refund terms, dispute process, and enterprise-specific provisions before commercial launch.*
"""


def _auth_css():
    st.markdown(
        """
        <style>
        :root{
            --cadivor-blue:#2563EB;
            --cadivor-blue-2:#1D4ED8;
            --cadivor-navy:#0F172A;
            --cadivor-slate:#475569;
            --cadivor-muted:#64748B;
            --cadivor-border:#E2E8F0;
            --cadivor-bg:#F3F6FA;
            --cadivor-soft:#F8FAFC;
            --cadivor-green:#16A34A;
            --cadivor-amber:#F59E0B;
            --cadivor-red:#EF4444;
            --shadow-sm:0 8px 20px rgba(15,23,42,.055);
            --shadow-md:0 18px 42px rgba(15,23,42,.08);
            --shadow-lg:0 30px 90px rgba(15,23,42,.12);
        }
        html, body, .stApp, [data-testid="stAppViewContainer"]{
            background:var(--cadivor-bg)!important;
            color:var(--cadivor-navy)!important;
            font-family:Inter, ui-sans-serif, system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif!important;
        }
        [data-testid="stHeader"]{
            background:rgba(243,246,250,.78)!important;
            border-bottom:0!important;
            backdrop-filter:blur(10px);
        }
        [data-testid="stToolbar"], [data-testid="stDecoration"]{display:none!important;}
        section[data-testid="stSidebar"]{display:none!important;}
        .cadivor-public{width:100%; max-width:1180px; margin:0 auto;}
        [data-testid="stMainBlockContainer"]:has(.cadivor-public),
        .block-container:has(.cadivor-public){
            width:min(1180px,96vw)!important;
            max-width:1180px!important;
            margin:0 auto!important;
            padding:1.8rem 1.3rem 4rem 1.3rem!important;
        }
        /* Auth login / signup card — centered, fixed width on all displays */
        [data-testid="stAppViewContainer"]:has(.auth-card-header){
            display:flex!important;
            flex-direction:column!important;
            align-items:center!important;
            background:var(--cadivor-bg)!important;
        }
        [data-testid="stMainBlockContainer"]:has(.auth-card-header),
        .main .block-container:has(.auth-card-header){
            width:min(480px,92vw)!important;
            max-width:480px!important;
            margin:7vh auto 48px auto!important;
            padding:38px 38px 34px 38px!important;
            background:#FFFFFF!important;
            border:1px solid #E2E8F0!important;
            border-top:6px solid #2563EB!important;
            border-radius:22px!important;
            box-shadow:0 28px 70px rgba(15,23,42,.13)!important;
            box-sizing:border-box!important;
        }
        [data-testid="stMainBlockContainer"]:has(.auth-card-header) > div,
        [data-testid="stMainBlockContainer"]:has(.auth-card-header) [data-testid="stVerticalBlock"],
        [data-testid="stMainBlockContainer"]:has(.auth-card-header) [data-testid="stForm"]{
            width:100%!important;
            max-width:100%!important;
        }
        [data-testid="stMainBlockContainer"]:has(.auth-card-header) .cadivor-back-home{
            display:flex!important;
            justify-content:center!important;
            width:100%!important;
            margin-top:18px!important;
        }
        .cadivor-nav{
            width:100%;
            display:flex;
            align-items:center;
            justify-content:space-between;
            gap:24px;
            margin:44px 0 34px 0;
            padding:0 4px;
        }
        .cadivor-brand{display:flex; align-items:center; gap:16px; color:var(--cadivor-navy)!important; font-weight:950; font-size:38px; letter-spacing:-.06em; text-decoration:none!important; border:0!important; box-shadow:none!important;}
        .cadivor-brand:visited,.cadivor-brand:hover,.cadivor-brand:active{color:var(--cadivor-navy)!important;text-decoration:none!important;border:0!important;box-shadow:none!important;}
        .cadivor-brand span{text-decoration:none!important;border-bottom:0!important;box-shadow:none!important;}
        .cadivor-mark{width:70px;height:70px;border-radius:20px;display:grid;place-items:center;background:linear-gradient(135deg,#3B82F6,#1D4ED8);color:#fff!important;font-weight:950;font-size:31px;box-shadow:0 18px 40px rgba(37,99,235,.28);}
        .cadivor-nav-links{display:flex;align-items:center;gap:28px;font-size:15px;font-weight:850;}
        .cadivor-nav-links a{color:#334155!important;text-decoration:none!important;}
        .cadivor-nav-links a:hover{color:var(--cadivor-blue)!important;text-decoration:none!important;opacity:1!important;filter:none!important;}
        .cadivor-signin{background:#fff;border:1px solid var(--cadivor-border);border-radius:12px;padding:11px 17px;color:#0F172A!important;box-shadow:var(--shadow-sm);}
        .cadivor-nav-cta{background:var(--cadivor-blue);border:1px solid var(--cadivor-blue);border-radius:12px;padding:11px 18px;color:#fff!important;box-shadow:0 14px 28px rgba(37,99,235,.23);}
        .cadivor-hero{
            display:grid;
            grid-template-columns:minmax(0,.92fr) minmax(650px,1.08fr);
            gap:60px;
            align-items:start;
            min-height:640px;
            padding:74px 72px;
            border:1px solid var(--cadivor-border);
            border-radius:30px;
            background:linear-gradient(135deg,#FFFFFF 0%,#F8FBFF 56%,#EAF3FF 100%);
            box-shadow:var(--shadow-lg);
            overflow:hidden;
            position:relative;
        }
        .cadivor-hero:before{content:"";position:absolute;right:-220px;top:-260px;width:620px;height:620px;border-radius:999px;background:radial-gradient(circle,rgba(37,99,235,.14),transparent 64%);pointer-events:none;}
        .cadivor-hero-content{position:relative;z-index:1;padding-top:0;align-self:start;margin-top:12px;}
        .cadivor-eyebrow{display:inline-flex;align-items:center;gap:9px;background:#EFF6FF;color:var(--cadivor-blue)!important;border:1px solid #BFDBFE;border-radius:999px;padding:9px 15px;font-size:12px;font-weight:950;letter-spacing:.105em;text-transform:uppercase;margin-bottom:24px;box-shadow:0 10px 24px rgba(37,99,235,.08);}
        .cadivor-title{font-size:clamp(58px,5.05vw,96px);line-height:.96;font-weight:950;letter-spacing:-.075em;color:var(--cadivor-navy)!important;margin:0 0 24px 0;max-width:840px;}
        .cadivor-title .blue{color:var(--cadivor-blue)!important;}
        .cadivor-subtitle{font-size:clamp(18px,1.25vw,22px);line-height:1.6;color:var(--cadivor-slate)!important;margin:0 0 34px 0;max-width:720px;}
        .cadivor-cta-row{display:flex;align-items:center;flex-wrap:wrap;gap:14px;margin-bottom:26px;}
        .cadivor-primary,.cadivor-secondary{display:inline-flex;align-items:center;justify-content:center;min-height:50px;border-radius:14px;padding:0 22px;font-weight:950;font-size:15px;text-decoration:none!important;}
        .cadivor-primary{background:var(--cadivor-blue);color:#fff!important;border:1px solid var(--cadivor-blue);box-shadow:0 18px 34px rgba(37,99,235,.24);}
        .cadivor-primary:hover,.cadivor-nav-cta:hover{background:var(--cadivor-blue-2)!important;color:#fff!important;border-color:var(--cadivor-blue-2)!important;text-decoration:none!important;filter:none!important;opacity:1!important;}
        a.cadivor-primary,a.cadivor-primary:visited,a.cadivor-primary:hover,a.cadivor-primary:active,a.cadivor-nav-cta,a.cadivor-nav-cta:visited,a.cadivor-nav-cta:hover,a.cadivor-nav-cta:active{color:#fff!important;text-decoration:none!important;}
        .cadivor-secondary{background:#fff;color:var(--cadivor-navy)!important;border:1px solid #CBD5E1;box-shadow:var(--shadow-sm);}
        .cadivor-proof{display:flex;align-items:center;flex-wrap:wrap;gap:22px;color:#475569!important;font-size:14px;font-weight:800;}

        .cadivor-public h1 a,.cadivor-public h2 a,.cadivor-public h3 a,.cadivor-public h4 a,.cadivor-title a,.section-heading h2 a{display:none!important;visibility:hidden!important;}
        .cadivor-public a[href^="#"]{display:none!important;}
        .cadivor-public .header-anchor,.cadivor-public .anchor-link,.cadivor-public a.anchor-link,.cadivor-public svg[class*="anchor"],.cadivor-public [data-testid*="stMarkdownContainer"] a[href^="#"]{display:none!important;visibility:hidden!important;width:0!important;height:0!important;overflow:hidden!important;}
        .cadivor-nav-links a,.cadivor-brand,.cadivor-primary,.cadivor-secondary,.cadivor-signin,.cadivor-nav-cta{cursor:pointer;transition:background .18s ease,color .18s ease,box-shadow .18s ease,transform .18s ease,border-color .18s ease;}
        .cadivor-nav-cta:hover,.cadivor-primary:hover{transform:translateY(-1px);box-shadow:0 18px 36px rgba(37,99,235,.28)!important;}
        .cadivor-signin:hover,.cadivor-secondary:hover{background:#F8FAFC!important;color:#0F172A!important;border-color:#94A3B8!important;text-decoration:none!important;opacity:1!important;filter:none!important;}
        .cadivor-eyebrow:before{content:"";width:8px;height:8px;border-radius:99px;background:#2563EB;box-shadow:0 0 0 4px rgba(37,99,235,.10);}
        .feature-card:hover,.solution-card:hover,.mini-card:hover,.resource-card:hover,.flow-step:hover{transform:translateY(-3px);box-shadow:0 22px 46px rgba(15,23,42,.09);border-color:#CBD5E1;}
        .feature-card,.solution-card,.mini-card,.resource-card,.flow-step{transition:transform .18s ease, box-shadow .18s ease, border-color .18s ease;}
        .cadivor-proof span{display:inline-flex;align-items:center;gap:8px;}.cadivor-check{width:22px;height:22px;border-radius:8px;display:grid;place-items:center;background:#EFF6FF;color:var(--cadivor-blue)!important;border:1px solid #BFDBFE;font-size:13px;}
        .product-window{position:relative;z-index:1;background:#fff;border:1px solid var(--cadivor-border);border-radius:24px;box-shadow:0 30px 80px rgba(15,23,42,.14);overflow:hidden;margin-top:0;}
        .product-top{height:50px;display:flex;align-items:center;justify-content:space-between;padding:0 18px;border-bottom:1px solid #E5E7EB;background:#fff;}
        .product-brand{display:flex;align-items:center;gap:10px;font-weight:950;color:#0F172A!important;}.product-logo{width:26px;height:26px;border-radius:8px;background:#2563EB;color:#fff!important;display:grid;place-items:center;font-weight:950;font-size:13px;}
        .product-app{display:grid;grid-template-columns:190px 1fr;min-height:475px;}.product-side{background:#F8FAFC;border-right:1px solid #E5E7EB;padding:18px 12px;}.product-nav{display:flex;align-items:center;gap:8px;border-radius:10px;padding:10px 12px;color:#475569!important;font-size:13px;font-weight:850;margin-bottom:5px;white-space:nowrap;}.product-nav.active{background:#EFF6FF;color:#2563EB!important;}.product-main{padding:24px;background:#fff;}.product-heading{display:flex;align-items:center;justify-content:space-between;margin-bottom:18px;}.product-heading strong{font-size:22px;color:#0F172A!important;letter-spacing:-.04em;}.product-btn{background:#2563EB;color:#fff!important;border-radius:10px;padding:9px 13px;font-size:12px;font-weight:900;}.product-kpis{display:grid;grid-template-columns:repeat(3,1fr);gap:12px;margin-bottom:16px;}.product-kpi{background:#fff;border:1px solid #E5E7EB;border-radius:15px;padding:15px;box-shadow:0 8px 18px rgba(15,23,42,.035);}.product-kpi span{display:block;color:#64748B!important;text-transform:uppercase;letter-spacing:.045em;font-size:11px;font-weight:900;margin-bottom:8px;}.product-kpi strong{font-size:30px;color:#0F172A!important;}.product-panels{display:grid;grid-template-columns:1fr .86fr;gap:14px;margin-bottom:16px;}.product-panel{border:1px solid #E5E7EB;border-radius:16px;padding:16px;min-height:150px;background:#fff;}.line-chart{height:95px;border-left:1px solid #E5E7EB;border-bottom:1px solid #E5E7EB;margin-top:20px;}.line-chart svg{width:100%;height:100%;overflow:visible}.donut-wrap{display:flex;gap:18px;align-items:center;justify-content:center;height:120px;}.donut{width:100px;height:100px;border-radius:50%;background:conic-gradient(#16A34A 0 48%,#F59E0B 48% 78%,#EF4444 78% 100%);display:grid;place-items:center;}.donut-inner{width:58px;height:58px;border-radius:50%;background:#fff;display:grid;place-items:center;color:#0F172A!important;font-weight:950;}.risk-legend{font-size:12px;color:#475569!important;line-height:1.9;font-weight:800}.legend-red,.legend-amber,.legend-green{display:inline-block;width:8px;height:8px;border-radius:50%;margin-right:7px}.legend-red{background:#EF4444}.legend-amber{background:#F59E0B}.legend-green{background:#16A34A}.product-table{border:1px solid #E5E7EB;border-radius:14px;overflow:hidden}.product-row{display:grid;grid-template-columns:1.3fr .8fr .8fr .8fr .6fr;border-bottom:1px solid #EEF2F7}.product-row:last-child{border-bottom:0}.product-cell{padding:10px 12px;color:#334155!important;font-size:12px;font-weight:750}.product-head .product-cell{background:#F8FAFC;color:#64748B!important;font-size:11px;text-transform:uppercase;letter-spacing:.04em;}
        .cadivor-section{padding:64px 0 10px 0;}.section-heading{text-align:center;max-width:900px;margin:0 auto 32px auto;}.section-heading h2{color:#0F172A!important;font-size:clamp(34px,2.4vw,52px);line-height:1.06;font-weight:950;letter-spacing:-.055em;margin:0 0 12px 0;}.section-heading p{color:#64748B!important;font-size:17px;line-height:1.65;margin:0;}.trusted-label{text-align:center;color:#64748B!important;font-weight:850;margin:36px 0 18px 0;}.trusted-logos{display:grid;grid-template-columns:repeat(6,1fr);gap:18px;align-items:center;text-align:center;color:#0F172A!important;font-size:26px;font-weight:950;}.trusted-logos span:nth-child(2),.trusted-logos span:nth-child(3),.trusted-logos span:nth-child(4){color:#2563EB!important;}
        .how-grid{display:grid;grid-template-columns:repeat(5,1fr);gap:16px;}.how-card,.pricing-card,.faq-card{background:#fff;border:1px solid #E5E7EB;border-radius:20px;box-shadow:var(--shadow-sm);}.feature-card,.solution-card{background:linear-gradient(180deg,#FFFFFF 0%,#FBFDFF 100%);border:1px solid #E5E7EB;border-radius:22px;box-shadow:0 16px 38px rgba(15,23,42,.06);position:relative;overflow:hidden;}.how-card{padding:22px;position:relative;}.step-num{width:34px;height:34px;border-radius:11px;background:#EFF6FF;color:#2563EB!important;display:grid;place-items:center;font-weight:950;margin-bottom:16px;}.how-card strong{display:block;color:#0F172A!important;font-size:18px;margin-bottom:8px;letter-spacing:-.02em;}.feature-card strong,.solution-card strong{display:block;color:#0F172A!important;font-size:20px;margin-bottom:10px;letter-spacing:-.035em;font-weight:950;}.how-card span{display:block;color:#64748B!important;font-size:14px;line-height:1.55;}.feature-card span,.solution-card span{display:block;color:#64748B!important;font-size:15px;line-height:1.68;font-weight:700;}
        .feature-grid{display:grid;grid-template-columns:repeat(3,1fr);gap:18px;}.feature-card{padding:30px;transition:transform .18s ease, box-shadow .18s ease,border-color .18s ease;}.feature-card:hover,.solution-card:hover,.pricing-card:hover{transform:translateY(-4px);box-shadow:0 26px 55px rgba(15,23,42,.09);border-color:#93C5FD;}.feature-icon{width:42px;height:42px;border-radius:14px;display:grid;place-items:center;background:#EFF6FF;color:#2563EB!important;font-weight:950;margin-bottom:16px;font-size:20px;}.solution-grid{display:grid;grid-template-columns:repeat(3,1fr);gap:18px;}.solution-card{padding:32px;transition:transform .18s ease, box-shadow .18s ease,border-color .18s ease;}.solution-card ul{margin:18px 0 0 0;padding:0;list-style:none;color:#475569!important;font-weight:800;line-height:2.05;}.solution-card li:before{content:"✓";color:#2563EB;font-weight:950;margin-right:8px;}.pricing-grid{display:grid;grid-template-columns:repeat(4,1fr);gap:18px;}.pricing-card{padding:28px;display:flex;flex-direction:column;min-height:330px;}.pricing-name{font-size:13px;text-transform:uppercase;letter-spacing:.07em;color:#64748B!important;font-weight:950;margin-bottom:14px;}.pricing-price{font-size:38px;color:#0F172A!important;font-weight:950;letter-spacing:-.05em;margin-bottom:8px;}.pricing-card p{color:#64748B!important;line-height:1.55;margin:0 0 18px 0;}.pricing-card ul{list-style:none;margin:0 0 24px 0;padding:0;color:#334155!important;font-weight:750;line-height:2;}.pricing-card li:before{content:"✓";color:#2563EB;font-weight:950;margin-right:8px;}.pricing-card .cadivor-primary,.pricing-card .cadivor-secondary{margin-top:auto;width:100%;}
        .faq-grid{display:grid;grid-template-columns:repeat(2,1fr);gap:16px;}.faq-card{padding:22px;}.faq-card strong{display:block;color:#0F172A!important;margin-bottom:8px;font-size:17px;}.faq-card span{color:#64748B!important;line-height:1.6;font-size:14px;}.footer{margin:70px 0 0 0;background:#0F172A;border-radius:24px;padding:34px;display:flex;justify-content:space-between;gap:28px;align-items:flex-start;box-shadow:0 24px 60px rgba(15,23,42,.20);}.footer strong{color:#fff!important;font-size:22px;}.footer p{color:#CBD5E1!important;max-width:520px;line-height:1.6;}.footer-links{display:flex;gap:22px;flex-wrap:wrap;}.footer-links a{color:#E2E8F0!important;text-decoration:none!important;font-weight:800;}
        .bottom-cta{margin:54px 0 0 0;background:linear-gradient(135deg,#0F172A,#1E3A8A);border-radius:24px;padding:30px 34px;display:flex;align-items:center;justify-content:space-between;gap:22px;box-shadow:0 26px 60px rgba(15,23,42,.20);}.bottom-cta strong{color:#fff!important;font-size:26px;display:block;margin-bottom:6px;}.bottom-cta span{color:#CBD5E1!important;font-size:15px;}
        /* Auth route */
        .auth-card-header{text-align:center;margin-bottom:26px;}.auth-card-logo{width:54px;height:54px;border-radius:16px;background:linear-gradient(135deg,#3B82F6,#1D4ED8);color:#fff!important;display:grid;place-items:center;margin:0 auto 14px auto;font-size:24px;font-weight:950;box-shadow:0 18px 38px rgba(37,99,235,.26);}.auth-card-title{color:#0F172A!important;font-size:26px;font-weight:950;letter-spacing:-.04em;margin:0 0 7px 0;}.auth-card-sub{color:#64748B!important;font-size:13px;font-weight:700;line-height:1.5;}.auth-card-brand-link{display:inline-block;text-decoration:none!important;color:inherit!important;}.auth-card-brand-link:hover{text-decoration:none!important;}.auth-card-brand-link:hover .auth-card-title{color:#2563EB!important;}.cadivor-back-home{display:inline-flex;align-items:center;justify-content:center;margin-top:16px;padding:8px 0;color:#2f6fed!important;text-decoration:none!important;font-size:13px;font-weight:900;transition:color .18s ease;}.cadivor-back-home:hover{color:#174ea6!important;text-decoration:underline!important;}.auth-heading{color:#0F172A!important;font-size:26px;font-weight:950;letter-spacing:-.045em;margin:0 0 8px 0;}.auth-copy{color:#64748B!important;font-size:15px;line-height:1.58;margin:0 0 18px 0;}.auth-strip{background:#F8FAFC;border:1px solid #E2E8F0;border-radius:14px;padding:12px 13px;color:#475569!important;font-size:12.5px;font-weight:780;line-height:1.45;margin:0 0 18px 0;}.auth-divider{height:1px;background:#E5E7EB;margin:18px -38px 20px -38px;}.terms-box{background:#F8FAFC;border:1px solid #E2E8F0;border-radius:14px;padding:12px 13px;color:#475569!important;font-size:12px;line-height:1.55;margin:8px 0 4px 0;}.auth-back{display:block;text-align:center;color:#334155!important;text-decoration:none!important;font-size:13px;font-weight:900;margin-top:16px;}
        [data-testid="stMainBlockContainer"]:has(.auth-card-header) div[data-testid="stRadio"]{background:#F8FAFC!important;border:1px solid #E5E7EB!important;border-radius:14px!important;padding:11px 13px 7px 13px!important;margin-bottom:16px!important;}[data-testid="stMainBlockContainer"]:has(.auth-card-header) div[data-testid="stRadio"] > label{color:#334155!important;font-weight:850!important;font-size:13px!important;}[data-testid="stMainBlockContainer"]:has(.auth-card-header) div[data-testid="stRadio"] label,[data-testid="stMainBlockContainer"]:has(.auth-card-header) div[data-testid="stRadio"] p{color:#0F172A!important;font-weight:800!important;}[data-testid="stMainBlockContainer"]:has(.auth-card-header) div[data-testid="stTextInput"] label,[data-testid="stMainBlockContainer"]:has(.auth-card-header) div[data-testid="stCheckbox"] label{color:#334155!important;font-weight:800!important;}[data-testid="stMainBlockContainer"]:has(.auth-card-header) div[data-testid="stTextInput"]{overflow:visible!important;margin-bottom:14px!important;width:100%!important;max-width:100%!important;}[data-testid="stMainBlockContainer"]:has(.auth-card-header) div[data-testid="stTextInput"] > div{overflow:visible!important;}[data-testid="stMainBlockContainer"]:has(.auth-card-header) div[data-testid="stTextInput"] [data-baseweb="input"]{background:#fff!important;border:1px solid #CBD5E1!important;border-radius:12px!important;min-height:48px!important;height:48px!important;box-shadow:none!important;outline:none!important;overflow:hidden!important;}[data-testid="stMainBlockContainer"]:has(.auth-card-header) div[data-testid="stTextInput"] [data-baseweb="input"]:focus-within{border-color:#2563EB!important;box-shadow:0 0 0 3px rgba(37,99,235,.14)!important;}[data-testid="stMainBlockContainer"]:has(.auth-card-header) div[data-testid="stTextInput"] [data-baseweb="input"]::before,[data-testid="stMainBlockContainer"]:has(.auth-card-header) div[data-testid="stTextInput"] [data-baseweb="input"]::after{display:none!important;content:none!important;}[data-testid="stMainBlockContainer"]:has(.auth-card-header) div[data-testid="stTextInput"] [data-baseweb="input"] > div,[data-testid="stMainBlockContainer"]:has(.auth-card-header) div[data-testid="stTextInput"] [data-baseweb="input"] > div:focus-within{border:0!important;outline:0!important;box-shadow:none!important;background:transparent!important;min-height:46px!important;}[data-testid="stMainBlockContainer"]:has(.auth-card-header) div[data-testid="stTextInput"] input,[data-testid="stMainBlockContainer"]:has(.auth-card-header) div[data-testid="stTextInput"] input[type="text"],[data-testid="stMainBlockContainer"]:has(.auth-card-header) div[data-testid="stTextInput"] input[type="password"],[data-testid="stMainBlockContainer"]:has(.auth-card-header) div[data-testid="stTextInput"] input[type="email"]{background:transparent!important;border:0!important;outline:0!important;border-radius:0!important;min-height:46px!important;height:46px!important;color:#0F172A!important;box-shadow:none!important;padding:0 14px!important;caret-color:#2563EB!important;}[data-testid="stMainBlockContainer"]:has(.auth-card-header) div[data-testid="stTextInput"] input:focus,[data-testid="stMainBlockContainer"]:has(.auth-card-header) div[data-testid="stTextInput"] input:focus-visible{border:0!important;outline:0!important;box-shadow:none!important;}[data-testid="stMainBlockContainer"]:has(.auth-card-header) div[data-testid="stTextInput"] button{min-height:46px!important;height:46px!important;width:44px!important;border:0!important;outline:0!important;background:#fff!important;border-radius:0!important;box-shadow:none!important;}[data-testid="stMainBlockContainer"]:has(.auth-card-header) div[data-testid="stCheckbox"] p{color:#334155!important;font-weight:750!important;font-size:13px!important;}[data-testid="stMainBlockContainer"]:has(.auth-card-header) div[data-testid="stFormSubmitButton"] > button,[data-testid="stMainBlockContainer"]:has(.auth-card-header) div.stButton > button{width:100%!important;min-height:50px!important;border-radius:13px!important;background:linear-gradient(135deg,#2563EB,#1D4ED8)!important;border:1px solid #2563EB!important;color:#fff!important;font-weight:900!important;box-shadow:0 18px 34px rgba(37,99,235,.24)!important;}[data-testid="stMainBlockContainer"]:has(.auth-card-header) div[data-testid="stFormSubmitButton"] > button:hover,[data-testid="stMainBlockContainer"]:has(.auth-card-header) div.stButton > button:hover{background:linear-gradient(135deg,#1D4ED8,#1E40AF)!important;border-color:#1D4ED8!important;color:#fff!important;}[data-testid="stMainBlockContainer"]:has(.auth-card-header) div[data-testid="stFormSubmitButton"] > button *,[data-testid="stMainBlockContainer"]:has(.auth-card-header) div.stButton > button *{color:#fff!important;}
        @media(max-width:700px){[data-testid="stMainBlockContainer"]:has(.auth-card-header),.main .block-container:has(.auth-card-header){margin:3vh auto 32px auto!important;width:94vw!important;max-width:94vw!important;padding:28px 22px!important;border-radius:18px!important;}.auth-divider{margin-left:-22px!important;margin-right:-22px!important;}}
        .page-section{padding-top:58px!important;} .compact-section{padding-top:42px!important;} .cadivor-nav-links a.active{color:#2563EB!important;background:#EFF6FF;border-radius:10px;padding:8px 10px;margin:-8px -10px;}

        .mini-grid{display:grid;grid-template-columns:repeat(3,1fr);gap:22px;margin-top:28px;}
        .mini-card{background:#fff;border:1px solid var(--cadivor-border);border-radius:18px;padding:26px;box-shadow:0 14px 34px rgba(15,23,42,.055);}
        .mini-card strong{display:block;color:#0F172A!important;font-size:17px;font-weight:950;margin-bottom:8px;}
        .mini-card span{display:block;color:#64748B!important;font-size:14px;line-height:1.6;font-weight:700;}
        .resource-grid{display:grid;grid-template-columns:repeat(3,1fr);gap:22px;margin-top:28px;}
        .resource-card{background:#fff;border:1px solid var(--cadivor-border);border-radius:18px;padding:26px;box-shadow:var(--shadow-sm);}
        .resource-card .resource-icon{width:42px;height:42px;border-radius:14px;display:grid;place-items:center;background:#EFF6FF;color:#2563EB!important;font-weight:950;margin-bottom:16px;}
        .resource-card strong{display:block;color:#0F172A!important;font-size:18px;font-weight:950;margin-bottom:8px;}
        .resource-card span{display:block;color:#64748B!important;font-size:14px;line-height:1.6;font-weight:700;}
        .solution-flow{display:grid;grid-template-columns:repeat(4,1fr);gap:16px;margin-top:26px;}
        .flow-step{background:#fff;border:1px solid var(--cadivor-border);border-radius:18px;padding:24px;box-shadow:0 14px 34px rgba(15,23,42,.055);}
        .flow-step b{display:block;color:#2563EB!important;font-size:13px;text-transform:uppercase;letter-spacing:.08em;margin-bottom:8px;}
        .flow-step strong{display:block;color:#0F172A!important;font-size:16px;margin-bottom:6px;}
        .flow-step span{display:block;color:#64748B!important;font-size:13px;line-height:1.5;font-weight:700;}
        @media(max-width:1200px){.cadivor-hero{grid-template-columns:1fr;padding:44px;}.product-window{max-width:900px}.trusted-logos{grid-template-columns:repeat(3,1fr)}.feature-grid,.solution-grid,.pricing-grid,.mini-grid,.resource-grid,.solution-flow{grid-template-columns:repeat(2,1fr)}.how-grid{grid-template-columns:repeat(2,1fr)}}
        @media(max-width:760px){.block-container:has(.cadivor-public){width:100%!important;padding-left:1rem!important;padding-right:1rem!important}.cadivor-nav{align-items:flex-start;flex-direction:column}.cadivor-nav-links{flex-wrap:wrap;gap:14px}.cadivor-hero{padding:28px;min-height:auto;border-radius:22px}.product-app{grid-template-columns:1fr}.product-side{display:none}.product-kpis,.product-panels,.feature-grid,.solution-grid,.pricing-grid,.faq-grid,.mini-grid,.resource-grid,.solution-flow{grid-template-columns:1fr}.trusted-logos{grid-template-columns:repeat(2,1fr);font-size:20px}.bottom-cta,.footer{flex-direction:column;align-items:flex-start}.how-grid{grid-template-columns:1fr}}
        </style>
        """,
        unsafe_allow_html=True,
    )




def _install_auth_submit_feedback() -> None:
    """No browser overlay is installed; Streamlit owns the auth transition."""
    return


def _render_back_to_marketing_link() -> None:
    _html(
        f'<a href="{CADIVOR_MARKETING_URL}" target="_self" class="cadivor-back-home">← Back to Cadivor</a>'
    )


def _render_auth_page(supabase, cookie_manager, initial_mode: str):
    st.markdown(
        f"""
        <div class="auth-card-header">
            <a href="{CADIVOR_MARKETING_URL}" target="_self" class="auth-card-brand-link">
                <div class="auth-card-logo">C</div>
                <div class="auth-card-title">Cadivor</div>
            </a>
            <div class="auth-card-sub">Engineering intelligence for modern electronics teams.</div>
        </div>
        <div class="auth-heading">Access your workspace</div>
        <p class="auth-copy">Sign in to Cadivor, or create a workspace to run your first BOM through Cadivor.</p>
        <div class="auth-strip">🔒 Your BOMs, saved analyses, reports, recommendations, and subscription usage stay connected to your Cadivor workspace.</div>
        <div class="auth-divider"></div>
        """,
        unsafe_allow_html=True,
    )

    options = ["Login", "Create Account"]
    with st.form("cadivor_auth_form", clear_on_submit=False, border=False):
        auth_mode = st.radio("Choose an option", options, index=options.index(initial_mode), horizontal=True)
        email = st.text_input("Email", placeholder="you@company.com")
        password = st.text_input("Password", type="password", placeholder="Enter your password")

        accepted_terms = True
        if auth_mode == "Create Account":
            st.markdown(
                """
                <div class="terms-box"><strong>Terms summary:</strong> Cadivor provides decision-support outputs only. You remain responsible for engineering validation, datasheet review, supplier confirmation, procurement decisions, and production release decisions.</div>
                """,
                unsafe_allow_html=True,
            )
            accepted_terms = st.checkbox("I agree to the Terms of Service and Privacy Policy.")
            with st.expander("View Terms of Service"):
                st.markdown(CADIVOR_TERMS)

        submit = st.form_submit_button(
            "Create Account" if auth_mode == "Create Account" else "Login",
            use_container_width=True,
        )

    # Authentication uses a deliberate two-run sequence. The submit run only
    # commits the request; the following run paints the transition surface
    # before any synchronous Supabase network call begins.
    if submit:
        if not email or not password:
            st.warning("Please enter your email and password.")
            return
        if auth_mode == "Create Account" and not accepted_terms:
            st.warning("Please accept the Terms of Service and Privacy Policy to create an account.")
            return
        st.session_state["cadivor_auth_submission"] = {
            "mode": auth_mode,
            "email": email,
            "password": password,
        }
        st.session_state["cadivor_auth_status"] = "signing_in"
        st.session_state["cadivor_root_state"] = APP_SIGNING_IN
        st.rerun()

    pending = st.session_state.get("cadivor_auth_submission")
    if isinstance(pending, dict):
        render_auth_transition(
            "Creating your secure workspace…"
            if pending.get("mode") == "Create Account"
            else "Opening your engineering workspace…"
        )
        try:
            if pending.get("mode") == "Create Account":
                response = supabase.auth.sign_up({
                    "email": pending.get("email", ""),
                    "password": pending.get("password", ""),
                })
                st.session_state.pop("cadivor_auth_submission", None)
                if getattr(response, "session", None):
                    mark_authenticated(response.user, response.session)
                    st.rerun()
                st.session_state["cadivor_auth_status"] = "signed_out"
                st.session_state["cadivor_root_state"] = APP_LOGIN
                st.success("Account created. Please check your email to confirm your account, then return here to log in.")
                return
            response = supabase.auth.sign_in_with_password({
                "email": pending.get("email", ""),
                "password": pending.get("password", ""),
            })
            st.session_state.pop("cadivor_auth_submission", None)
            if not getattr(response, "session", None):
                st.session_state["cadivor_auth_status"] = "signed_out"
                st.session_state["cadivor_root_state"] = APP_LOGIN
                st.error("Login failed: no session was returned. Please confirm your email and try again.")
                return
            mark_authenticated(response.user, response.session)
            st.rerun()
        except Exception as error:
            st.session_state.pop("cadivor_auth_submission", None)
            st.session_state["cadivor_auth_status"] = "signed_out"
            st.session_state["cadivor_root_state"] = APP_LOGIN
            st.error(f"Authentication failed: {error}")
            return

    _render_back_to_marketing_link()



def _html(markup: str):
    """Render HTML without Markdown indentation turning it into a code block."""
    st.markdown(dedent(markup).strip(), unsafe_allow_html=True)


def _nav(active: str = "home"):
    items = [("features", "Features"), ("solutions", "Solutions"), ("pricing", "Pricing"), ("resources", "Resources")]
    links = "".join(
        f'<a class="{"active" if key == active else ""}" href="?public={key}" target="_self">{label}</a>'
        for key, label in items
    )
    _html(f"""
    <div class="cadivor-public">
      <div class="cadivor-nav">
        <a class="cadivor-brand" href="?" target="_self">
          <div class="cadivor-mark">C</div><span>Cadivor</span>
        </a>
        <div class="cadivor-nav-links">
          {links}
          <a href="#" aria-disabled="true" class="cadivor-signin">Sign In</a>
          <a href="#" aria-disabled="true" class="cadivor-nav-cta">Get Started</a>
        </div>
      </div>
    </div>
    """)


def _dashboard_mockup():
    return """
    <div class="product-window">
      <div class="product-top">
        <div class="product-brand"><span class="product-logo">C</span><span>Cadivor</span></div>
        <div style="color:#94A3B8;font-weight:850;font-size:12px;">Live workspace</div>
      </div>
      <div class="product-app">
        <div class="product-side">
          <div class="product-nav active">⌂ Dashboard</div>
          <div class="product-nav">▦ BOM Analyzer</div>
          <div class="product-nav">◌ Analyses</div>
          <div class="product-nav">✦ Alternative Finder</div>
          <div class="product-nav">▣ Reports</div>
          <div class="product-nav">⚙ Settings</div>
        </div>
        <div class="product-main">
          <div class="product-heading"><strong>Dashboard</strong><span class="product-btn">+ New Analysis</span></div>
          <div class="product-kpis">
            <div class="product-kpi"><span>Overall BOM Risk</span><strong>72</strong></div>
            <div class="product-kpi"><span>High Risk</span><strong>18</strong></div>
            <div class="product-kpi"><span>Alternatives</span><strong>78</strong></div>
          </div>
          <div class="product-panels">
            <div class="product-panel"><strong style="color:#0F172A!important;">BOM Risk Trend</strong><div class="line-chart"><svg viewBox="0 0 420 100"><polyline points="0,30 60,35 120,62 180,50 240,76 300,80 360,54 420,38" fill="none" stroke="#2563EB" stroke-width="4" stroke-linecap="round" stroke-linejoin="round"/><g fill="#2563EB"><circle cx="0" cy="30" r="4"/><circle cx="60" cy="35" r="4"/><circle cx="120" cy="62" r="4"/><circle cx="180" cy="50" r="4"/><circle cx="240" cy="76" r="4"/><circle cx="300" cy="80" r="4"/><circle cx="360" cy="54" r="4"/><circle cx="420" cy="38" r="4"/></g></svg></div></div>
            <div class="product-panel"><strong style="color:#0F172A!important;">Risk Distribution</strong><div class="donut-wrap"><div class="donut"><div class="donut-inner">100</div></div><div class="risk-legend"><div><span class="legend-red"></span>High Risk</div><div><span class="legend-amber"></span>Medium Risk</div><div><span class="legend-green"></span>Low Risk</div></div></div></div>
          </div>
          <div class="product-table">
            <div class="product-row product-head"><div class="product-cell">File Name</div><div class="product-cell">Date</div><div class="product-cell">Components</div><div class="product-cell">Risk</div><div class="product-cell">Action</div></div>
            <div class="product-row"><div class="product-cell">Industrial_Controller_BOM.xlsx</div><div class="product-cell">May 12</div><div class="product-cell">100</div><div class="product-cell">Medium</div><div class="product-cell">View</div></div>
            <div class="product-row"><div class="product-cell">Power_Supply_RevB.csv</div><div class="product-cell">May 11</div><div class="product-cell">78</div><div class="product-cell">Low</div><div class="product-cell">View</div></div>
            <div class="product-row"><div class="product-cell">IoT_Device_BOM.xlsx</div><div class="product-cell">May 10</div><div class="product-cell">80</div><div class="product-cell">High</div><div class="product-cell">View</div></div>
          </div>
        </div>
      </div>
    </div>
    """


def _render_home_page():
    _nav("home")
    _html(f"""
    <div class="cadivor-public">
      <section class="cadivor-hero">
        <div class="cadivor-hero-content">
          <div class="cadivor-eyebrow">Engineering intelligence for modern electronics teams</div>
          <h1 class="cadivor-title"><span>Run every BOM through Cadivor.</span><br><span class="blue">Find better alternatives.</span></h1>
          <p class="cadivor-subtitle">Turn BOM spreadsheets into lifecycle, supplier, risk, and replacement-part intelligence your engineering and sourcing teams can review with confidence.</p>
          <div class="cadivor-cta-row">
            <a class="cadivor-primary" href="#" aria-disabled="true">Get Started</a>
            <a class="cadivor-secondary" href="?public=features" target="_self">See How It Works</a>
          </div>
          <div class="cadivor-proof">
            <span><span class="cadivor-check">✓</span>No credit card required</span>
            <span><span class="cadivor-check">✓</span>AI-assisted risk insights</span>
            <span><span class="cadivor-check">✓</span>CSV & Excel export</span>
          </div>
        </div>
        {_dashboard_mockup()}
      </section>
      <div class="trusted-label">Built for engineering and sourcing teams</div>
      <div class="trusted-logos"><span>DigiKey</span><span>Mouser</span><span>Newark</span><span>CSV</span><span>Excel</span><span>Octopart soon</span></div>
      <section class="cadivor-section" id="overview">
        <div class="section-heading"><h2>Engineering BOM review without spreadsheet chaos</h2><p>Cadivor gives teams a cleaner way to review component health, sourcing exposure, and replacement paths before small risks become production problems.</p></div>
        <div class="feature-grid">
          <div class="feature-card"><div class="feature-icon">▣</div><strong>Lifecycle Intelligence</strong><span>Identify EOL, NRND, replacement-suggested, and unknown lifecycle exposure before design release.</span></div>
          <div class="feature-card"><div class="feature-icon">↔</div><strong>Alternative Finder</strong><span>Compare replacement candidates with lifecycle, sourcing, and implementation context.</span></div>
          <div class="feature-card"><div class="feature-icon">▤</div><strong>Executive Reports</strong><span>Export clean BOM risk summaries for engineering, sourcing, and leadership review.</span></div>
        </div>
      </section>
      <div class="bottom-cta"><div><strong>Ready to reduce your BOM risk?</strong><span>Run it through Cadivor and review supplier, lifecycle, and alternative-part intelligence in minutes.</span></div><a class="cadivor-primary" href="#" aria-disabled="true">Get Started</a></div>
      <div class="footer"><div><strong>Cadivor</strong><p>Engineering intelligence for electronics teams. Analyze BOM risk, compare alternatives, and make sourcing decisions with confidence.</p></div><div class="footer-links"><a href="?public=features" target="_self">Features</a><a href="?public=solutions" target="_self">Solutions</a><a href="?public=pricing" target="_self">Pricing</a><a href="?public=resources" target="_self">Resources</a><a href="#" aria-disabled="true">Sign In</a></div></div>
    </div>
    """)


def _render_features_page():
    _nav("features")
    _html("""
    <div class="cadivor-public">
      <section class="cadivor-section page-section" id="features">
        <div class="section-heading"><h2>How Cadivor works</h2><p>A structured BOM review workflow built for engineering, sourcing, and leadership teams.</p></div>
        <div class="how-grid">
          <div class="how-card"><div class="step-num">1</div><strong>Upload BOM</strong><span>Import CSV or Excel files with part numbers and quantities.</span></div>
          <div class="how-card"><div class="step-num">2</div><strong>Analyze risk</strong><span>Cadivor checks lifecycle, supplier coverage, inventory, and sourcing exposure.</span></div>
          <div class="how-card"><div class="step-num">3</div><strong>Review issues</strong><span>See high-risk parts, supplier limitations, and lifecycle warnings in one place.</span></div>
          <div class="how-card"><div class="step-num">4</div><strong>Find alternatives</strong><span>Compare replacement candidates ranked by engineering and sourcing confidence.</span></div>
          <div class="how-card"><div class="step-num">5</div><strong>Export reports</strong><span>Generate engineering-ready reports for sourcing, procurement, and management review.</span></div>
        </div>
        <div class="mini-grid">
          <div class="mini-card"><strong>Repeatable review process</strong><span>Use the same review flow for every project instead of one-off spreadsheet checks.</span></div>
          <div class="mini-card"><strong>Engineering-first outputs</strong><span>Cadivor highlights risks, but keeps final judgment with your engineering team.</span></div>
          <div class="mini-card"><strong>Built for expansion</strong><span>Lifecycle, supplier, monitoring, reports, and alternatives can grow in one workspace.</span></div>
        </div>
      </section>
      <section class="cadivor-section compact-section">
        <div class="section-heading"><h2>Everything you need to review BOM risk with confidence</h2><p>Supplier data, lifecycle checks, risk scoring, monitoring, and alternatives in one clean engineering workspace.</p></div>
        <div class="feature-grid">
          <div class="feature-card"><div class="feature-icon">▣</div><strong>Lifecycle Intelligence</strong><span>Identify EOL, NRND, replacement-suggested, and unknown lifecycle components before they affect production.</span></div>
          <div class="feature-card"><div class="feature-icon">◌</div><strong>Supplier Intelligence</strong><span>Review stock, supplier concentration, lead time, and availability signals across integrated suppliers.</span></div>
          <div class="feature-card"><div class="feature-icon">↗</div><strong>AI-Assisted Risk Scoring</strong><span>Prioritize components using lifecycle, sourcing, inventory, and supplier factors without overselling automation.</span></div>
          <div class="feature-card"><div class="feature-icon">↔</div><strong>Alternative Finder</strong><span>Find compatible replacements ranked by availability, lifecycle health, sourcing confidence, and implementation risk.</span></div>
          <div class="feature-card"><div class="feature-icon">▤</div><strong>Executive Reports</strong><span>Export clear BOM health reports that engineering, sourcing, and leadership teams can review together.</span></div>
          <div class="feature-card"><div class="feature-icon">◎</div><strong>Monitoring</strong><span>Track saved parts for stock, lifecycle, and supplier changes that may affect ongoing projects.</span></div>
        </div>
      </section>
      <div class="bottom-cta"><div><strong>Ready to run your next BOM through Cadivor?</strong><span>Review lifecycle, supplier exposure, risk, and alternatives in one connected workspace.</span></div><a class="cadivor-primary" href="#" aria-disabled="true">Get Started</a></div>
      <div class="footer"><div><strong>Cadivor</strong><p>Engineering intelligence for electronics teams. Analyze BOM risk, compare alternatives, and make sourcing decisions with confidence.</p></div><div class="footer-links"><a href="?public=features" target="_self">Features</a><a href="?public=solutions" target="_self">Solutions</a><a href="?public=pricing" target="_self">Pricing</a><a href="?public=resources" target="_self">Resources</a><a href="#" aria-disabled="true">Sign In</a></div></div>
    </div>
    """)

def _render_solutions_page():
    _nav("solutions")
    _html("""
    <div class="cadivor-public">
      <section class="cadivor-section page-section" id="solutions">
        <div class="section-heading"><h2>Built for the teams behind modern electronics</h2><p>One shared source of BOM intelligence for engineering validation, sourcing review, and management visibility.</p></div>
        <div class="solution-grid">
          <div class="solution-card"><div class="feature-icon">⚙</div><strong>Electronics Engineers</strong><span>Validate component risk before design release.</span><ul><li>Review lifecycle status</li><li>Compare replacements</li><li>Document engineering concerns</li></ul></div>
          <div class="solution-card"><div class="feature-icon">▤</div><strong>Procurement Teams</strong><span>Understand supplier and market exposure earlier.</span><ul><li>Check stock and supplier count</li><li>Track sourcing concentration</li><li>Prepare alternate sourcing paths</li></ul></div>
          <div class="solution-card"><div class="feature-icon">◉</div><strong>Engineering Managers</strong><span>See portfolio-level BOM health and reporting.</span><ul><li>Monitor saved analyses</li><li>Review high-risk projects</li><li>Export decision-ready reports</li></ul></div>
        </div>
      </section>
      <section class="cadivor-section compact-section">
        <div class="section-heading"><h2>One workflow from risk detection to decision</h2><p>Keep the full review path connected: upload, analyze, compare, decide, and export.</p></div>
        <div class="solution-flow">
          <div class="flow-step"><b>01</b><strong>Design review</strong><span>Check early BOMs for lifecycle exposure and sourcing concentration.</span></div>
          <div class="flow-step"><b>02</b><strong>Sourcing review</strong><span>Compare suppliers, inventory signals, and likely procurement bottlenecks.</span></div>
          <div class="flow-step"><b>03</b><strong>Alternate review</strong><span>Shortlist replacement candidates with compatibility and implementation context.</span></div>
          <div class="flow-step"><b>04</b><strong>Leadership review</strong><span>Export concise reports so managers can see project risk clearly.</span></div>
        </div>
      </section>
      <div class="bottom-cta"><div><strong>Ready to run your next BOM through Cadivor?</strong><span>Review lifecycle, supplier exposure, risk, and alternatives in one connected workspace.</span></div><a class="cadivor-primary" href="#" aria-disabled="true">Get Started</a></div>
      <div class="footer"><div><strong>Cadivor</strong><p>Engineering intelligence for electronics teams. Analyze BOM risk, compare alternatives, and make sourcing decisions with confidence.</p></div><div class="footer-links"><a href="?public=features" target="_self">Features</a><a href="?public=solutions" target="_self">Solutions</a><a href="?public=pricing" target="_self">Pricing</a><a href="?public=resources" target="_self">Resources</a><a href="#" aria-disabled="true">Sign In</a></div></div>
    </div>
    """)

def _render_pricing_page():
    _nav("pricing")
    _html("""
    <div class="cadivor-public">
      <section class="cadivor-section page-section" id="pricing">
        <div class="section-heading"><h2>Simple plans for BOM review workflows</h2><p>Start small, then scale as your team reviews more projects and monitors more parts.</p></div>
        <div class="pricing-grid">
          <div class="pricing-card"><div class="pricing-name">Starter</div><div class="pricing-price">$29/mo</div><p>For individual engineers reviewing smaller BOMs.</p><ul><li>5 BOMs/month</li><li>10 parts per BOM</li><li>CSV/XLSX export</li></ul><a class="cadivor-secondary" href="#" aria-disabled="true">Get Started</a></div>
          <div class="pricing-card"><div class="pricing-name">Pro</div><div class="pricing-price">$99/mo</div><p>For engineers reviewing multiple BOMs.</p><ul><li>10 BOMs/month</li><li>20 parts per BOM</li><li>Alternative Finder</li><li>Supplier intelligence</li></ul><a class="cadivor-primary" href="#" aria-disabled="true">Start Pro</a></div>
          <div class="pricing-card"><div class="pricing-name">Business</div><div class="pricing-price">$299/mo</div><p>For teams standardizing BOM risk review.</p><ul><li>25 BOMs/month</li><li>100 parts per BOM</li><li>Advanced reports</li><li>Team workflows</li></ul><a class="cadivor-secondary" href="#" aria-disabled="true">Start Business</a></div>
          <div class="pricing-card"><div class="pricing-name">Enterprise</div><div class="pricing-price">Custom</div><p>For organizations with broader component intelligence needs.</p><ul><li>Higher limits</li><li>Custom workflows</li><li>Priority support</li><li>Supplier integrations</li></ul><a class="cadivor-secondary" href="#" aria-disabled="true">Contact Us</a></div>
        </div>
      </section>
      <div class="bottom-cta"><div><strong>Ready to run your next BOM through Cadivor?</strong><span>Review lifecycle, supplier exposure, risk, and alternatives in one connected workspace.</span></div><a class="cadivor-primary" href="#" aria-disabled="true">Get Started</a></div>
      <div class="footer"><div><strong>Cadivor</strong><p>Engineering intelligence for electronics teams. Analyze BOM risk, compare alternatives, and make sourcing decisions with confidence.</p></div><div class="footer-links"><a href="?public=features" target="_self">Features</a><a href="?public=solutions" target="_self">Solutions</a><a href="?public=pricing" target="_self">Pricing</a><a href="?public=resources" target="_self">Resources</a><a href="#" aria-disabled="true">Sign In</a></div></div>
    </div>
    """)


def _render_resources_page():
    _nav("resources")
    _html("""
    <div class="cadivor-public">
      <section class="cadivor-section page-section" id="resources">
        <div class="section-heading"><h2>Resources</h2><p>Documentation, examples, and engineering guidance will live here as Cadivor grows.</p></div>
        <div class="resource-grid">
          <div class="resource-card"><div class="resource-icon">📘</div><strong>Getting Started Guide</strong><span>Learn how to format a BOM, upload a file, read risk scores, and export your first report.</span></div>
          <div class="resource-card"><div class="resource-icon">🧩</div><strong>BOM Template</strong><span>Use a clean CSV or Excel template with part number and quantity columns.</span></div>
          <div class="resource-card"><div class="resource-icon">🛡</div><strong>Engineering Disclaimer</strong><span>Understand how Cadivor supports decisions without replacing professional engineering review.</span></div>
        </div>
      </section>
      <section class="cadivor-section compact-section">
        <div class="section-heading"><h2>Common questions</h2><p>Quick answers for engineers, sourcing teams, and early Cadivor users.</p></div>
        <div class="faq-grid">
          <div class="faq-card"><strong>What file formats are supported?</strong><span>Cadivor supports CSV and Excel BOM files with part number and quantity columns.</span></div>
          <div class="faq-card"><strong>Does Cadivor replace engineering review?</strong><span>No. Cadivor is a decision-support tool. Engineers remain responsible for datasheet, supplier, and production validation.</span></div>
          <div class="faq-card"><strong>Which suppliers are supported?</strong><span>Current integrations include DigiKey, Mouser, and Newark, with Octopart planned.</span></div>
          <div class="faq-card"><strong>Can I export reports?</strong><span>Yes. Cadivor supports report exports for engineering and sourcing review.</span></div>
          <div class="faq-card"><strong>How are alternatives ranked?</strong><span>Cadivor considers lifecycle, sourcing availability, supplier data, and engineering compatibility signals.</span></div>
          <div class="faq-card"><strong>Is AI used?</strong><span>Cadivor uses AI-assisted analysis alongside supplier data and engineering rules, while keeping final decisions with your team.</span></div>
        </div>
      </section>
      <div class="bottom-cta"><div><strong>Ready to run your next BOM through Cadivor?</strong><span>Review lifecycle, supplier exposure, risk, and alternatives in one connected workspace.</span></div><a class="cadivor-primary" href="#" aria-disabled="true">Get Started</a></div>
      <div class="footer"><div><strong>Cadivor</strong><p>Engineering intelligence for electronics teams. Analyze BOM risk, compare alternatives, and make sourcing decisions with confidence.</p></div><div class="footer-links"><a href="?public=features" target="_self">Features</a><a href="?public=solutions" target="_self">Solutions</a><a href="?public=pricing" target="_self">Pricing</a><a href="?public=resources" target="_self">Resources</a><a href="#" aria-disabled="true">Sign In</a></div></div>
    </div>
    """)

def _render_landing_page():
    try:
        page = st.query_params.get("public", "home")
    except Exception:
        page = "home"
    if page == "features":
        _render_features_page()
    elif page == "solutions":
        _render_solutions_page()
    elif page == "pricing":
        _render_pricing_page()
    elif page == "resources":
        _render_resources_page()
    else:
        _render_home_page()

def show_auth_ui(supabase, cookie_manager=None):
    """Render exactly one signed-out/authentication surface per run."""
    _auth_css()
    inject_core_premium_ui_auth()
    state = str(st.session_state.get("cadivor_root_state") or APP_PUBLIC)

    # Public header actions intentionally use stable query links so they remain
    # inside the custom marketing navigation rather than floating Streamlit
    # widgets. Translate those links once at the signed-out boundary.
    try:
        requested_auth = st.query_params.get("auth", "")
    except Exception:
        requested_auth = ""
    if isinstance(requested_auth, (list, tuple)):
        requested_auth = requested_auth[0] if requested_auth else ""
    requested_auth = str(requested_auth or "").strip().lower()
    if state == APP_PUBLIC and requested_auth in {"login", "signup"}:
        state = APP_SIGNUP if requested_auth == "signup" else APP_LOGIN
        st.session_state["cadivor_root_state"] = state
        st.session_state["cadivor_auth_intent_applied"] = True
        st.session_state.pop("cadivor_auth_submission", None)

    if state == APP_SIGNING_IN:
        pending = st.session_state.get("cadivor_auth_submission")
        if not isinstance(pending, dict):
            st.session_state["cadivor_root_state"] = APP_LOGIN
            st.rerun()
        # The transition is the only visible surface in this state.
        render_auth_transition(
            "Creating your secure workspace…"
            if pending.get("mode") == "Create Account"
            else "Opening your engineering workspace…"
        )
        try:
            if pending.get("mode") == "Create Account":
                response = supabase.auth.sign_up({
                    "email": pending.get("email", ""),
                    "password": pending.get("password", ""),
                })
                st.session_state.pop("cadivor_auth_submission", None)
                if getattr(response, "session", None):
                    mark_authenticated(response.user, response.session)
                    st.rerun()
                st.session_state["cadivor_auth_status"] = "signed_out"
                st.session_state["cadivor_root_state"] = APP_LOGIN
                st.session_state["cadivor_auth_notice"] = "Account created. Check your email to confirm the account, then sign in."
                st.rerun()
            response = supabase.auth.sign_in_with_password({
                "email": pending.get("email", ""),
                "password": pending.get("password", ""),
            })
            st.session_state.pop("cadivor_auth_submission", None)
            if not getattr(response, "session", None):
                st.session_state["cadivor_auth_status"] = "signed_out"
                st.session_state["cadivor_root_state"] = APP_LOGIN
                st.session_state["cadivor_auth_error"] = "Login failed: no session was returned."
                st.rerun()
            mark_authenticated(response.user, response.session)
            st.rerun()
        except Exception as error:
            st.session_state.pop("cadivor_auth_submission", None)
            st.session_state["cadivor_auth_status"] = "signed_out"
            st.session_state["cadivor_root_state"] = APP_LOGIN
            st.session_state["cadivor_auth_error"] = f"Authentication failed: {error}"
            st.rerun()
        st.stop()

    if state in (APP_LOGIN, APP_SIGNUP):
        notice = st.session_state.pop("cadivor_auth_notice", None)
        error = st.session_state.pop("cadivor_auth_error", None)
        if notice:
            st.success(notice)
        if error:
            st.error(error)
        _render_auth_page(
            supabase=supabase,
            cookie_manager=cookie_manager,
            initial_mode="Create Account" if state == APP_SIGNUP else "Login",
        )
        return

    from src.marketing_site import render_marketing_site
    st.session_state["cadivor_root_state"] = APP_PUBLIC
    render_marketing_site()
