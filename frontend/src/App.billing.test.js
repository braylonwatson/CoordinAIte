import { render, screen, fireEvent } from "@testing-library/react";
import App from "./App";
import { apiFetch, restoreSession } from "./api";

jest.mock("./BackgroundParticles", () => () => null);
jest.mock("./api", () => ({
  apiFetch: jest.fn(), restoreSession: jest.fn(), signOut: jest.fn(),
  setGuestGameToken: jest.fn(), closeLivePredictions: jest.fn(), AUTH_EXPIRED: "auth-expired",
}));

const status = (active) => ({
  tier: active ? "tier2" : "free", tier2_access: active,
  tier2_models_available: true, subscription_status: active ? "active" : null,
});

beforeEach(() => {
  jest.clearAllMocks();
  sessionStorage.clear();
  window.history.replaceState({}, "", "/?success=true");
  restoreSession.mockResolvedValue({ user_id: 1, username: "Coach", email: "coach@example.com" });
  apiFetch.mockImplementation(async (path) => ({
    ok: true, json: async () => path === "/games" ? [] : status(false),
  }));
});

afterEach(() => window.history.replaceState({}, "", "/"));

test("checkout return shows $10 and waits for server-confirmed access", async () => {
  const view = render(<App />);
  expect(await screen.findByText("$10 / month")).toBeInTheDocument();
  expect(screen.queryByRole("button", { name: "Tier 2 Active" })).not.toBeInTheDocument();
  expect(screen.getByText(/Checking your subscription/)).toBeInTheDocument();
  apiFetch.mockResolvedValue({ ok: true, json: async () => status(true) });
  fireEvent.click(screen.getByRole("button", { name: "Refresh subscription" }));
  expect(await screen.findByRole("button", { name: "Tier 2 Active" })).toBeInTheDocument();
  view.unmount();
});

test("success query alone cannot grant access to a signed-out visitor", async () => {
  restoreSession.mockResolvedValue(null);
  render(<App />);
  expect(await screen.findByRole("button", { name: /continue as guest/i })).toBeInTheDocument();
  expect(screen.queryByRole("button", { name: "Tier 2 Active" })).not.toBeInTheDocument();
  expect(apiFetch).not.toHaveBeenCalled();
});
