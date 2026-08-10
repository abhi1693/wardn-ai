/* eslint-disable @typescript-eslint/no-namespace -- Cypress extends its global command interface. */
import type {} from "@testing-library/cypress";
import "@testing-library/cypress/add-commands";
import { mount } from "cypress/react";

import "../../app/globals.css";
import { TooltipProvider } from "@/components/atoms/tooltip";

Cypress.Commands.add("mount", (component, options) =>
  mount(<TooltipProvider delayDuration={0}>{component}</TooltipProvider>, options)
);

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
