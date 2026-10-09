import { useCallback, useEffect, useMemo, useState } from "react";
import { apiFetch } from "./api";
import "./AccountPages.css";


function displayTime(value) {
  if (!value) return "Unknown";
  const parsed = new Date(value);
  return Number.isNaN(parsed.getTime()) ? "Unknown" : parsed.toLocaleString();
}


function responseMessage(data, fallback) {
  return typeof data?.detail === "string" ? data.detail : fallback;
}


export function OwnerUsersPage({ onBack }) {
  const [users, setUsers] = useState([]);
  const [requests, setRequests] = useState([]);
  const [search, setSearch] = useState("");
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const [busyRequestId, setBusyRequestId] = useState(null);

  const refresh = useCallback(async () => {
    setLoading(true);
    setError("");
    try {
      const [usersResponse, requestsResponse] = await Promise.all([
        apiFetch("/owner/users"),
        apiFetch("/owner/refund-requests"),
      ]);
      const [usersData, requestsData] = await Promise.all([
        usersResponse.json(), requestsResponse.json(),
      ]);
      if (!usersResponse.ok) throw new Error(responseMessage(usersData, "Could not load users."));
      if (!requestsResponse.ok) throw new Error(responseMessage(requestsData, "Could not load refund requests."));
      setUsers(Array.isArray(usersData) ? usersData : []);
      setRequests(Array.isArray(requestsData) ? requestsData : []);
    } catch (loadError) {
      setError(loadError.message || "Could not load owner data.");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => { refresh(); }, [refresh]);

  const filteredUsers = useMemo(() => {
    const term = search.trim().toLowerCase();
    if (!term) return users;
    return users.filter((user) =>
      `${user.user_id} ${user.username} ${user.email} ${user.tier} ${user.subscription_status || ""}`
        .toLowerCase().includes(term)
    );
  }, [users, search]);

  const decideRequest = async (request, decision) => {
    if (decision === "approve") {
      const confirmed = window.confirm(
        `Approve refund request #${request.id}? CoordinAIte will cancel the Stripe subscription immediately, remove Tier 2 access, and refund the latest eligible paid invoice.`
      );
      if (!confirmed) return;
    }
    setBusyRequestId(request.id);
    setError("");
    setNotice("");
    try {
      const response = await apiFetch(`/owner/refund-requests/${request.id}/${decision}`, { method: "POST" });
      const data = await response.json();
      if (!response.ok) throw new Error(responseMessage(data, "Could not update the refund request."));
      setNotice(data.resolution_message || (decision === "approve" ? "Refund request approved." : "Refund request denied."));
      await refresh();
    } catch (actionError) {
      setError(actionError.message || "Could not update the refund request.");
      await refresh();
    } finally {
      setBusyRequestId(null);
    }
  };

  const pendingCount = requests.filter((request) => ["pending", "failed"].includes(request.status)).length;
  const tier2Count = users.filter((user) => user.tier === "tier2").length;
  const totalSavedGames = users.reduce((sum, user) => sum + (user.saved_game_count || 0), 0);

  return (
    <main className="account-page owner-page">
      <header className="account-page-header">
        <div>
          <p className="account-eyebrow">CoordinAIte owner console</p>
          <h1>Users</h1>
          <p className="account-subtitle">Account and subscription overview, plus refund requests waiting for your decision.</p>
        </div>
        <div className="account-header-actions">
          <button className="account-button secondary" onClick={onBack}>Back to app</button>
          <button className="account-button primary" onClick={refresh} disabled={loading}>
            {loading ? "Refreshing…" : "Refresh"}
          </button>
        </div>
      </header>

      {error && <div className="account-alert error" role="alert">{error}</div>}
      {notice && <div className="account-alert success" role="status">{notice}</div>}

      <section className="account-stat-grid" aria-label="User totals">
        <div className="account-stat"><span>Registered users</span><strong>{users.length}</strong></div>
        <div className="account-stat"><span>Tier 2 accounts</span><strong>{tier2Count}</strong></div>
        <div className="account-stat"><span>Refunds to review</span><strong>{pendingCount}</strong></div>
        <div className="account-stat"><span>Saved games</span><strong>{totalSavedGames}</strong></div>
      </section>

      <section className="account-panel">
        <div className="account-panel-heading">
          <div>
            <h2>Refund requests</h2>
            <p>Approving cancels the subscription and removes Tier 2 immediately, then refunds the latest eligible paid invoice in Stripe.</p>
          </div>
        </div>
        {loading && !requests.length ? <p className="account-empty">Loading refund requests…</p> : requests.length === 0 ? (
          <p className="account-empty">No refund requests yet.</p>
        ) : (
          <div className="refund-request-list">
            {requests.map((request) => (
              <article className="refund-request-card" key={request.id}>
                <div className="refund-request-topline">
                  <div>
                    <h3>Request #{request.id} · {request.username || `User ${request.user_id}`}</h3>
                    <p>{request.email} · Account ID {request.user_id} · {displayTime(request.created_at)}</p>
                  </div>
                  <span className={`account-status status-${request.status}`}>{request.status}</span>
                </div>
                <div className="refund-reason">{request.reason}</div>
                <div className="refund-request-meta">
                  <span>Email notification: {request.notified_at ? `sent ${displayTime(request.notified_at)}` : "not sent"}</span>
                  {request.refund_amount_cents > 0 && (
                    <span>Refund: {new Intl.NumberFormat(undefined, { style: "currency", currency: (request.refund_currency || "usd").toUpperCase() }).format(request.refund_amount_cents / 100)}</span>
                  )}
                  {request.stripe_refund_id && <span>Stripe refund {request.stripe_refund_id} · {request.stripe_refund_status || "status unknown"}</span>}
                  {request.resolution_message && <span>{request.resolution_message}</span>}
                </div>
                {["pending", "failed"].includes(request.status) && (
                  <div className="account-row-actions">
                    <button className="account-button primary" disabled={busyRequestId === request.id} onClick={() => decideRequest(request, "approve")}>
                      {busyRequestId === request.id ? "Processing…" : "Approve & refund"}
                    </button>
                    <button className="account-button secondary" disabled={busyRequestId === request.id} onClick={() => decideRequest(request, "deny")}>
                      Deny request
                    </button>
                  </div>
                )}
              </article>
            ))}
          </div>
        )}
      </section>

      <section className="account-panel">
        <div className="account-panel-heading users-heading">
          <div>
            <h2>All users</h2>
            <p>Passwords, password hashes, and Stripe customer identifiers are never returned to this page.</p>
          </div>
          <label className="account-search">
            <span className="visually-hidden">Search users</span>
            <input value={search} onChange={(event) => setSearch(event.target.value)} placeholder="Search name, email, tier…" />
          </label>
        </div>
        {loading && !users.length ? <p className="account-empty">Loading users…</p> : filteredUsers.length === 0 ? (
          <p className="account-empty">No users match that search.</p>
        ) : (
          <div className="account-table-scroll">
            <table className="account-table">
              <thead><tr>
                <th>Account</th><th>Tier / status</th><th>Signed up</th><th>Last account update</th>
                <th>Last login</th><th>Subscription started</th><th>Subscription ended</th>
                <th>Status changed</th><th>Saved games</th>
              </tr></thead>
              <tbody>
                {filteredUsers.map((user) => (
                  <tr key={user.user_id}>
                    <td><strong>{user.username}</strong><small>{user.email}</small><small>ID {user.user_id}</small></td>
                    <td><span className={`account-status ${user.tier === "tier2" ? "status-active" : "status-free"}`}>{user.tier}</span><small>{user.subscription_status || "no subscription"}</small></td>
                    <td>{displayTime(user.created_at)}</td>
                    <td>{displayTime(user.updated_at)}</td>
                    <td>{displayTime(user.last_login_at)}</td>
                    <td>{displayTime(user.subscription_started_at)}</td>
                    <td>{displayTime(user.subscription_ended_at)}</td>
                    <td>{displayTime(user.subscription_status_changed_at)}</td>
                    <td>{user.saved_game_count}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </section>
    </main>
  );
}


export function RefundRequestPage({ user, canRequest, onBack }) {
  const [reason, setReason] = useState("");
  const [request, setRequest] = useState(null);
  const [loading, setLoading] = useState(true);
  const [sending, setSending] = useState(false);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");

  const refresh = useCallback(async () => {
    setLoading(true);
    try {
      const response = await apiFetch("/me/refund-request");
      const data = await response.json();
      if (!response.ok) throw new Error(responseMessage(data, "Could not load your refund request."));
      setRequest(data);
    } catch (loadError) {
      setError(loadError.message || "Could not load your request.");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => { refresh(); }, [refresh]);

  const requestOpen = request && ["pending", "processing"].includes(request.status);
  const submit = async (event) => {
    event.preventDefault();
    setError("");
    setNotice("");
    if (reason.trim().length < 10) {
      setError("Please share at least a sentence about why you are requesting a refund.");
      return;
    }
    setSending(true);
    try {
      const response = await apiFetch("/me/refund-request", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ reason: reason.trim() }),
      });
      const data = await response.json();
      if (!response.ok) throw new Error(responseMessage(data, "Could not submit your refund request."));
      setRequest(data);
      setReason("");
      setNotice(data.message || "Your request was saved for review.");
    } catch (submitError) {
      setError(submitError.message || "Could not submit your request.");
    } finally {
      setSending(false);
    }
  };

  return (
    <main className="account-page refund-page">
      <header className="account-page-header">
        <div>
          <p className="account-eyebrow">CoordinAIte support</p>
          <h1>Refund request</h1>
          <p className="account-subtitle">Tell us what happened. Your request will be reviewed by the CoordinAIte owner.</p>
        </div>
        <button className="account-button secondary" onClick={onBack}>Back</button>
      </header>

      <section className="account-panel refund-chat-panel">
        <div className="chat-message from-support">
          <span className="chat-avatar">C</span>
          <div><strong>CoordinAIte Support</strong><p>Hi {user?.name || "there"}. What would you like us to know about your refund request?</p></div>
        </div>
        {request && (
          <div className="chat-message from-user">
            <span className="chat-avatar">You</span>
            <div><strong>{user?.email}</strong><p>{request.reason}</p><small>Request #{request.id} · {request.status} · {displayTime(request.created_at)}</small></div>
          </div>
        )}
        {loading && <p className="account-empty">Checking your previous requests…</p>}
        {error && <div className="account-alert error" role="alert">{error}</div>}
        {notice && <div className="account-alert success" role="status">{notice}</div>}
        {request?.resolution_message && <div className="refund-resolution">{request.resolution_message}</div>}

        {!loading && !requestOpen && canRequest && (
          <form className="refund-compose" onSubmit={submit}>
            <label htmlFor="refund-reason">Your message</label>
            <textarea
              id="refund-reason"
              rows="5"
              maxLength="2000"
              value={reason}
              onChange={(event) => setReason(event.target.value)}
              placeholder="Please describe why you would like a refund…"
            />
            <div className="refund-compose-footer">
              <span>{reason.length}/2000</span>
              <button className="account-button primary" type="submit" disabled={sending}>
                {sending ? "Sending…" : "Send request"}
              </button>
            </div>
          </form>
        )}
        {!loading && !canRequest && !requestOpen && (
          <div className="refund-resolution">An active Tier 2 subscription is required to submit a refund request.</div>
        )}
        {requestOpen && (
          <div className="refund-resolution">
            Your request is waiting for owner review. Your subscription remains active until the owner approves a refund.
          </div>
        )}

        <p className="refund-privacy-note">
          This request includes your registered email and account ID and is sent to support@coordinaite.net. If approved, your Stripe subscription will be canceled and Tier 2 access removed immediately.
        </p>
      </section>
    </main>
  );
}
