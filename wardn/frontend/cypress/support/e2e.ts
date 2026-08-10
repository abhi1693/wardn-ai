/* eslint-disable @typescript-eslint/no-namespace -- Cypress extends its global command interface. */
import type {} from "@testing-library/cypress";
import "@testing-library/cypress/add-commands";

Cypress.on("uncaught:exception", (error) => {
  // Cypress instruments the document before Next hydrates its root element in production mode.
  if (error.message.includes("Minified React error #418") && error.message.includes("args[]=HTML")) {
    return false;
  }
  return undefined;
});

export type BackendRequest = {
  body?: Record<string, unknown>;
  method: string;
  path: string;
  query?: Record<string, string>;
};

Cypress.Commands.add("resetBackend", (overrides: Record<string, unknown> = {}) => {
  return cy
    .env(["mockBackendUrl"])
    .then(({ mockBackendUrl }) =>
      cy.request("POST", `${String(mockBackendUrl)}/__test/reset`, overrides)
    );
});

Cypress.Commands.add("login", () => {
  cy.env(["sessionCookieName"]).then(({ sessionCookieName }) => {
    cy.setCookie(String(sessionCookieName), "test-session");
  });
});

Cypress.Commands.add("backendRequests", () => {
  return cy.env(["mockBackendUrl"]).then(({ mockBackendUrl }) =>
    cy
      .request<{ requests: BackendRequest[] }>(`${String(mockBackendUrl)}/__test/requests`)
      .its("body.requests")
  );
});

Cypress.Commands.add("assertDesktopFit", () => {
  cy.document().then((document) => {
    const viewportWidth = document.defaultView?.innerWidth ?? 0;
    const controls = Array.from(
      document.querySelectorAll<HTMLElement>(
        "a[href], button:not([disabled]), input:not([type='hidden']), select, [role='button'], [role='tab']"
      )
    );
    const offscreenControls = controls.filter((element) => {
      const style = getComputedStyle(element);
      const rect = element.getBoundingClientRect();
      return (
        style.display !== "none" &&
        style.visibility !== "hidden" &&
        rect.width > 0 &&
        rect.height > 0 &&
        (rect.left < -1 || rect.right > viewportWidth + 1 || rect.top < -1)
      );
    });

    expect(document.documentElement.scrollWidth).to.be.at.most(viewportWidth);
    expect(
      offscreenControls.map(
        (element) => element.getAttribute("aria-label") || element.textContent?.trim()
      )
    ).to.deep.equal([]);
  });
});

declare global {
  namespace Cypress {
    interface Chainable {
      assertDesktopFit(): Chainable<void>;
      backendRequests(): Chainable<BackendRequest[]>;
      login(): Chainable<void>;
      resetBackend(overrides?: Record<string, unknown>): Chainable<Response<unknown>>;
    }
  }
}

export {};
