import { useEffect, useState } from "react";
import { api, fmtDateTime } from "../api.js";

export const rupees = (n) => `₹${Math.round(n ?? 0).toLocaleString("en-IN")}`;

// Loads Razorpay's checkout script once, on demand.
function loadRazorpay() {
  if (window.Razorpay) return Promise.resolve();
  return new Promise((resolve, reject) => {
    const el = document.createElement("script");
    el.src = "https://checkout.razorpay.com/v1/checkout.js";
    el.onload = resolve;
    el.onerror = () => reject(new Error("Could not load Razorpay. Check your internet connection."));
    document.body.appendChild(el);
  });
}

const METHODS = [
  { id: "upi", label: "UPI", icon: "📱" },
  { id: "card", label: "Card", icon: "💳" },
  { id: "netbanking", label: "Net banking", icon: "🏦" },
];

function Receipt({ r, me, year }) {
  return (
    <div className="receipt" id="fee-receipt">
      <div className="row between"><strong>Transport fee receipt</strong><span className="badge ok">Paid</span></div>
      <dl>
        <dt>Student</dt><dd>{me.name} · {me.username}</dd>
        <dt>Academic year</dt><dd>{year}</dd>
        <dt>Amount</dt><dd>{rupees(r.amount)}</dd>
        <dt>Method</dt><dd>{METHODS.find((m) => m.id === r.method)?.label ?? r.method}</dd>
        <dt>Reference</dt><dd><code>{r.reference}</code></dd>
        <dt>Date</dt><dd>{fmtDateTime(r.created_at)}</dd>
      </dl>
      <p className="small muted">Demo receipt: no real money was charged.</p>
    </div>
  );
}

/** Transport-fee status, demo checkout and receipt. Calls onPaid() after a successful payment. */
export default function FeeCard({ me, onPaid }) {
  const [fee, setFee] = useState(null);
  const [open, setOpen] = useState(false);
  const [method, setMethod] = useState("upi");
  const [stage, setStage] = useState("choose"); // choose | processing | done
  const [error, setError] = useState("");

  const load = () => api("/me/fee").then(setFee).catch((e) => setError(e.message));
  useEffect(() => { load(); }, []);

  const pay = async () => {
    setStage("processing"); setError("");
    try {
      await new Promise((r) => setTimeout(r, 1200)); // feels like a gateway round-trip
      await api("/me/fee/pay", { method: "POST", body: { method } });
      await load();
      setStage("done"); // the parent is told on close, so the receipt stays on screen until then
    } catch (e) { setError(e.message); setStage("choose"); }
  };

  // Real gateway: server creates an order, Razorpay Checkout collects the payment,
  // and the server verifies Razorpay's signature before marking the fee paid.
  const payRazorpay = async () => {
    setError("");
    try {
      await loadRazorpay();
      const o = await api("/me/fee/order", { method: "POST" });
      const rzp = new window.Razorpay({
        key: o.key_id, order_id: o.order_id, amount: o.amount, currency: o.currency,
        name: o.name, description: o.description, prefill: o.prefill, notes: o.notes,
        theme: { color: "#2563eb" },
        handler: async (resp) => {
          setOpen(true); setStage("processing");
          try {
            await api("/me/fee/verify", { method: "POST", body: resp });
            await load();
            setStage("done");
          } catch (e) { setOpen(false); setError(e.message); }
        },
        modal: { ondismiss: () => setError("Payment cancelled. You can try again any time.") },
      });
      rzp.on("payment.failed", (r) => setError(`Payment failed: ${r.error?.description || "please try again"}`));
      rzp.open();
    } catch (e) { setError(e.message); }
  };

  const close = () => {
    if (stage === "processing") return;
    setOpen(false);
    if (stage === "done") onPaid?.();
  };

  if (!fee) return null;
  return (
    <section className={`card ${fee.paid ? "" : "fee-due"}`}>
      <div className="row between wrap">
        <h3>Transport fee · {fee.academic_year}</h3>
        <span className={`badge ${fee.paid ? "ok" : "bad"}`}>{fee.paid ? "Paid" : "Pending"}</span>
      </div>
      {!fee.paid && (
        <>
          <p><span className="fee-amount">{rupees(fee.amount)}</span> <span className="muted">for the academic year</span></p>
          <p className="small muted">Pay your fee to book a seat on the bus. Payment goes to the college.</p>
          {fee.gateway === "razorpay" ? (
            <>
              <button className="btn primary" onClick={payRazorpay}>Pay now</button>
              <p className="small muted">Secure payment by Razorpay: UPI, cards, net banking.
                {fee.test_mode && <strong> Test mode: no real money is charged.</strong>}</p>
            </>
          ) : (
            <button className="btn primary" onClick={() => { setOpen(true); setStage("choose"); }}>Pay now</button>
          )}
        </>
      )}
      {fee.paid && fee.receipt && (
        <details>
          <summary className="small">View receipt</summary>
          <Receipt r={fee.receipt} me={me} year={fee.academic_year} />
          <button className="btn small" onClick={() => window.print()}>Print / save as PDF</button>
        </details>
      )}
      {fee.paid && !fee.receipt && <p className="small muted">Paid at the college accounts office.</p>}
      {error && <div className="alert error">{error}</div>}

      {open && (
        <div className="modal-backdrop" onClick={close}>
          <div className="modal card" onClick={(e) => e.stopPropagation()} role="dialog" aria-label="Pay transport fee">
            {stage === "choose" && (
              <>
                <h3>Pay {rupees(fee.amount)}</h3>
                <div className="alert info small">
                  <strong>Demo checkout.</strong> No real money is charged and no payment details are collected.
                  The college's real payment gateway will be connected at setup.
                </div>
                <div className="method-grid">
                  {METHODS.map((m) => (
                    <button key={m.id} className={`method ${method === m.id ? "selected" : ""}`} onClick={() => setMethod(m.id)}>
                      <span className="method-icon">{m.icon}</span>{m.label}
                    </button>
                  ))}
                </div>
                <div className="row between">
                  <button className="btn ghost" onClick={() => setOpen(false)}>Cancel</button>
                  <button className="btn primary" onClick={pay}>Pay {rupees(fee.amount)} (demo)</button>
                </div>
              </>
            )}
            {stage === "processing" && <div className="center-pad"><div className="spinner" /><p>Processing payment…</p></div>}
            {stage === "done" && fee.receipt && (
              <>
                <h3>✅ Payment successful</h3>
                <Receipt r={fee.receipt} me={me} year={fee.academic_year} />
                <div className="row between">
                  <button className="btn" onClick={() => window.print()}>Print receipt</button>
                  <button className="btn primary" onClick={close}>Done</button>
                </div>
              </>
            )}
          </div>
        </div>
      )}
    </section>
  );
}
