/** A pure routing gate for signed Checkout events. No browser return grants credit. */
export function oneTimeBOMAction(
  eventType: string,
  session: {
    mode?: string | null;
    payment_status?: string | null;
    metadata?: Record<string, string> | null;
    client_reference_id?: string | null;
  },
): "ignore" | "pending" | "close" | "fulfill" | null {
  if (!["checkout.session.completed", "checkout.session.async_payment_succeeded",
        "checkout.session.async_payment_failed", "checkout.session.expired"].includes(eventType)) {
    return null;
  }
  if (session.mode !== "payment") return null; // Existing subscription path.
  if (session.metadata?.cadivor_product !== "single_bom_report") return "ignore";
  const orderId = session.metadata?.cadivor_order_id;
  const userId = session.metadata?.user_id;
  if (!orderId || !userId || session.client_reference_id !== orderId) {
    throw new Error("One-time checkout is missing order identity.");
  }
  if (eventType === "checkout.session.expired" ||
      eventType === "checkout.session.async_payment_failed") return "close";
  return session.payment_status === "paid" ? "fulfill" : "pending";
}
