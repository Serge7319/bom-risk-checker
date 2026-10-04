import test from "node:test";
import assert from "node:assert/strict";
import { oneTimeBOMAction } from "../supabase/functions/stripe-webhook/one_time_bom_event.ts";

const order = {
  mode: "payment",
  payment_status: "paid",
  client_reference_id: "order-1",
  metadata: {
    cadivor_product: "single_bom_report",
    cadivor_order_id: "order-1",
    user_id: "user-1",
  },
};

test("paid one-time checkout is routed to fulfillment", () => {
  assert.equal(oneTimeBOMAction("checkout.session.completed", order), "fulfill");
  assert.equal(oneTimeBOMAction("checkout.session.async_payment_succeeded", order), "fulfill");
});

test("redirect or delayed payment cannot grant an analysis", () => {
  assert.equal(oneTimeBOMAction("checkout.session.completed", {
    ...order, payment_status: "unpaid",
  }), "pending");
  assert.equal(oneTimeBOMAction("checkout.session.expired", order), "close");
  assert.equal(oneTimeBOMAction("checkout.session.async_payment_failed", order), "close");
});

test("subscription checkout and unrelated payments keep their own paths", () => {
  assert.equal(oneTimeBOMAction("checkout.session.completed", {
    ...order, mode: "subscription",
  }), null);
  assert.equal(oneTimeBOMAction("checkout.session.completed", {
    ...order, metadata: { cadivor_product: "other" },
  }), "ignore");
});

test("product identity must match the Checkout reference", () => {
  assert.throws(() => oneTimeBOMAction("checkout.session.completed", {
    ...order, client_reference_id: "different",
  }), /identity/);
});
