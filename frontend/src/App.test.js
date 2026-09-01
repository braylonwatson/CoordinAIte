import { render, screen } from "@testing-library/react";
import App from "./App";


test("renders the CoordinAIte authentication entry point", () => {
  render(<App />);

  expect(screen.getByRole("button", { name: /login/i })).toBeInTheDocument();
  expect(screen.getByRole("button", { name: /sign up/i })).toBeInTheDocument();
  expect(
    screen.getByRole("button", { name: /continue as guest/i })
  ).toBeInTheDocument();
});
