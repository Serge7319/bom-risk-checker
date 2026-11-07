/** Pre-launch Terms of Service shown during account creation (aligned with Streamlit auth). */

export const TERMS_URL = "https://www.cadivor.com/#/terms";
export const PRIVACY_URL = "https://www.cadivor.com/#/privacy";

export const TERMS_SUMMARY =
  "Cadivor provides decision-support outputs only. You remain responsible for engineering validation, datasheet review, supplier confirmation, procurement decisions, and production release decisions.";

export const CADIVOR_TERMS_SECTIONS: Array<{ title: string; body: string }> = [
  {
    title: "1. Decision-support service",
    body: "Cadivor provides software-based component lifecycle, sourcing, supplier, inventory, risk, alternative-part, reporting, monitoring, and AI-assisted engineering intelligence for informational and decision-support purposes. Cadivor does not replace professional engineering judgment, datasheet review, supplier confirmation, qualification testing, procurement review, regulatory review, manufacturing review, or production-release approval. You remain responsible for validating outputs before relying on them in a design, sourcing, procurement, compliance, manufacturing, or production workflow.",
  },
  {
    title: "2. Accounts and authorized use",
    body: "You are responsible for maintaining accurate account information, protecting account credentials, and ensuring that people using your workspace are authorized to do so. You may not misuse the service, interfere with its operation, attempt unauthorized access, or use Cadivor for unlawful activity.",
  },
  {
    title: "3. Customer data and BOM ownership",
    body: "You retain ownership of BOMs and other content you upload. You grant Cadivor permission to process that content only as reasonably necessary to provide analysis, reporting, monitoring, account administration, support, security, service reliability, and product operation. You must not upload unlawful data or confidential third-party, export-controlled, restricted, regulated, or highly sensitive information unless you have the legal right and appropriate authorization to process it through the service.",
  },
  {
    title: "4. Supplier data and recommendations",
    body: "Cadivor may use distributor APIs, supplier records, public sources, third-party data, software rules, and AI-assisted analysis. Availability, lifecycle status, pricing, stock, lead times, risk scores, compatibility assessments, and alternative recommendations may be incomplete, delayed, inaccurate, or unsuitable for a particular design. You are responsible for confirming component specifications, fit, form, function, regulatory status, sourcing terms, and supplier information before purchasing, qualifying, or releasing a component.",
  },
  {
    title: "5. Plans, trials, billing, and changes",
    body: "Plan features and usage limits are described on the Pricing page and may vary by subscription. Standard new workspaces receive a 14-day trial with no card required. Accounts created through the one-time report checkout path do not receive trial analyses; they can pay once for one full BOM report or choose a subscription. A one-time report purchase does not renew. When a standard trial ends, saved work remains available, and creating new analyses requires a paid plan. Existing grandfathered beta access continues until Cadivor ends it. Paid subscriptions, renewal, taxes, refunds, and cancellation terms will be presented during checkout and in the final commercial agreement.",
  },
  {
    title: "6. Availability and service changes",
    body: "Cadivor may modify features, integrations, limits, or availability to improve the service, address security or legal requirements, or respond to third-party service changes. We will use reasonable efforts to communicate material changes that affect paid customers.",
  },
  {
    title: "7. Suspension and termination",
    body: "Cadivor may suspend or terminate access for abuse, misuse, nonpayment, security risk, violation of these Terms, or activity that may harm the service or other users. Customers may stop using the service and cancel eligible subscriptions through the available account or billing process.",
  },
  {
    title: "8. Disclaimers",
    body: "To the extent permitted by law, Cadivor is provided “as is” and “as available.” Cadivor does not warrant uninterrupted availability, complete accuracy, merchantability, non-infringement, or fitness for a particular purpose.",
  },
  {
    title: "9. Limitation of liability",
    body: "To the maximum extent permitted by law, Cadivor and its owners, officers, employees, contractors, suppliers, service providers, and affiliates will not be liable for indirect, incidental, consequential, special, punitive, procurement, production, recall, lost-profit, lost-data, business-interruption, design-failure, regulatory, or manufacturing damages arising from use of the service.",
  },
  {
    title: "10. Contact",
    body: "Questions about these Terms may be sent to legal@cadivor.com with “Terms” in the subject line.",
  },
];
