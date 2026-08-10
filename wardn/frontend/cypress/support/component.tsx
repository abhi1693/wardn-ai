/* eslint-disable @typescript-eslint/no-namespace -- Cypress extends its global command interface. */
import type {} from "@testing-library/cypress";
import "@testing-library/cypress/add-commands";
import { mount } from "cypress/react";

import "../../app/globals.css";

Cypress.Commands.add("mount", mount);

beforeEach(() => {
  cy.document().then((document) => {
    document.documentElement.className = "light";
    document.documentElement.style.colorScheme = "light";
  });
  cy.viewport(1440, 900);
});

declare global {
  namespace Cypress {
    interface Chainable {
      mount: typeof mount;
    }
  }
}

export {};
