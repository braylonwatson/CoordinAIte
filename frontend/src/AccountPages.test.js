import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { OwnerUsersPage, RefundRequestPage } from "./AccountPages";
import { apiFetch } from "./api";

jest.mock("./api", () => ({ apiFetch: jest.fn() }));

const jsonResponse = (data, ok = true) => ({ ok, json: async () => data });

beforeEach(() => jest.clearAllMocks());

test("owner page loads account and subscription timestamps without exposing private credential fields", async () => {
  apiFetch.mockImplementation(async (path) => path === "/owner/users"
    ? jsonResponse([{
      user_id: 8, username: "Coach", email: "coach@example.com", tier: "tier2",
      subscription_status: "active", created_at: "2026-10-09T10:00:00Z",
      last_login_at: "2026-10-09T12:00:00Z", subscription_started_at: null,
      subscription_ended_at: null, saved_game_count: 2,
    }])
    : jsonResponse([]));

  render(<OwnerUsersPage onBack={() => {}} />);
  expect(await screen.findByRole("heading", { name: "Users" })).toBeInTheDocument();
  expect(await screen.findByText("coach@example.com")).toBeInTheDocument();
  expect(screen.getByText("2", { selector: "td" })).toBeInTheDocument();
  expect(screen.getByText("All users")).toBeInTheDocument();
});

test("refund form sends the signed-in user's message to the refund request endpoint", async () => {
  apiFetch
    .mockResolvedValueOnce(jsonResponse(null))
    .mockResolvedValueOnce(jsonResponse({
      id: 14, reason: "I would like a refund because I no longer need Tier 2.",
      status: "pending", created_at: "2026-10-09T12:00:00Z",
      notification_sent: true, message: "Your request was sent to support for owner review.",
    }));

  render(<RefundRequestPage user={{ name: "Coach", email: "coach@example.com" }} canRequest onBack={() => {}} />);
  const input = await screen.findByLabelText("Your message");
  const reason = "I would like a refund because I no longer need Tier 2.";
  fireEvent.change(input, { target: { value: reason } });
  fireEvent.click(screen.getByRole("button", { name: "Send request" }));

  await waitFor(() => expect(apiFetch).toHaveBeenCalledWith("/me/refund-request", expect.objectContaining({ method: "POST" })));
  expect(apiFetch.mock.calls[1][1].body).toBe(JSON.stringify({ reason }));
  expect(await screen.findByText("Your request was sent to support for owner review.")).toBeInTheDocument();
  expect(await screen.findByText(/waiting for owner review/i)).toBeInTheDocument();
});
