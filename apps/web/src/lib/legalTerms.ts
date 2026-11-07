/**
 * Canonical published legal pages (marketing-web / www.cadivor.com).
 * Expandable copy must match those pages exactly — do not invent terms.
 */

export const TERMS_URL = "https://www.cadivor.com/#/terms";
export const PRIVACY_URL = "https://www.cadivor.com/#/privacy";

/** Version identifiers persisted server-side on acceptance. */
export const TERMS_VERSION = "cadivor.com-terms-v1";
export const PRIVACY_VERSION = "cadivor.com-privacy-v1";

/** Exact section copy from marketing-web/index.html data-page="terms". */
export const PUBLISHED_TERMS = {
  title: "Terms of Service",
  subtitle: "Conditions governing access to and use of Cadivor.",
  sections: [
    {
      title: "Use of the service",
      body: "Users are responsible for authorized use of their accounts and for reviewing engineering recommendations before acting on them.",
    },
    {
      title: "Engineering responsibility",
      body: "Cadivor provides decision support and does not replace professional engineering judgment, validation, qualification, or regulatory review.",
    },
    {
      title: "Customer data",
      body: "Customers retain ownership of their uploaded data and grant Cadivor the limited rights required to provide the service.",
    },
    {
      title: "Availability and changes",
      body: "Features may evolve as the platform develops. Material terms will be updated when necessary.",
    },
    {
      title: "Contact",
      body: "Legal and terms inquiries can be sent to legal@cadivor.com.",
    },
  ],
} as const;

/** Exact section copy from marketing-web/index.html data-page="privacy". */
export const PUBLISHED_PRIVACY = {
  title: "Privacy Policy",
  subtitle: "How Cadivor collects, uses, and protects information.",
  sections: [
    {
      title: "Information we collect",
      body: "Cadivor may collect account information, uploaded BOM data, product usage information, and communications submitted to us.",
    },
    {
      title: "How information is used",
      body: "Information is used to provide, secure, improve, and support the service, communicate with customers, and comply with legal obligations.",
    },
    {
      title: "Data sharing",
      body: "Cadivor does not sell personal information. Data may be shared with service providers required to operate the platform under appropriate safeguards.",
    },
    {
      title: "Contact",
      body: "Privacy questions can be sent to legal@cadivor.com.",
    },
  ],
} as const;
