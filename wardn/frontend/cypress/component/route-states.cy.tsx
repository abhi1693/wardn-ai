import { AppShellError } from "@/components/templates/app-shell-error";
import { AppShellLoading } from "@/components/templates/app-shell-loading";

describe("route states", () => {
  it("keeps the desktop shell stable while a workspace route loads", () => {
    cy.mount(<AppShellLoading label="Loading workspace" />);

    cy.findByRole("status", { name: "Loading workspace" })
      .should("be.visible")
      .and("have.attr", "aria-busy", "true");
    cy.findByText("Wardn AI").should("be.visible");
    cy.get("aside").should("have.css", "width", "260px");
    cy.get('[data-testid="route-loading"]').should("have.class", "max-w-[1360px]");
  });

  it("renders loading surfaces correctly in dark theme", () => {
    cy.document().then((document) => {
      document.documentElement.classList.remove("light");
      document.documentElement.classList.add("dark");
      document.documentElement.style.colorScheme = "dark";
    });
    cy.mount(<AppShellLoading label="Loading organization" />);

    cy.findByRole("status", { name: "Loading organization" }).should("be.visible");
    cy.get("main").should("have.class", "bg-background");
  });

  it("offers retry and a safe exit when a workspace route fails", () => {
    const reset = cy.stub().as("reset");
    cy.mount(<AppShellError error={new Error("backend unavailable")} reset={reset} scope="workspace" />);

    cy.findByRole("alert").should("contain.text", "Workspace unavailable");
    cy.findByRole("button", { name: "Try again" }).click();
    cy.get("@reset").should("have.been.calledOnce");
    cy.findByRole("link", { name: "Organizations" }).should("have.attr", "href", "/org");
  });
});
