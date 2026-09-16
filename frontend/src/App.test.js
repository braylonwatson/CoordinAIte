import { render, screen } from "@testing-library/react";
import App from "./App";

jest.mock("./BackgroundParticles", () => () => null);


test("renders the CoordinAIte authentication entry point", async () => {
  global.fetch = jest.fn().mockResolvedValue({ status: 401, ok: false });
  render(<App />);

  expect(await screen.findByRole("button", { name: /login/i })).toBeInTheDocument();
  expect(screen.getByRole("button", { name: /sign up/i })).toBeInTheDocument();
  expect(
    screen.getByRole("button", { name: /continue as guest/i })
  ).toBeInTheDocument();
});
