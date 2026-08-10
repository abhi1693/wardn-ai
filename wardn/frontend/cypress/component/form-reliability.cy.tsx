import { useState } from "react";

import { Button } from "@/components/atoms/button";
import { Input } from "@/components/atoms/input";
import { FormErrorSummary } from "@/components/molecules/form-error-summary";
import { FormField } from "@/components/molecules/form-field";
import { FormSection } from "@/components/organisms/form-section";
import { StickyFormActions } from "@/components/organisms/sticky-form-actions";
import { useUnsavedChanges } from "@/hooks/use-unsaved-changes";

function UnsavedChangesHarness() {
  const [name, setName] = useState("");
  const [left, setLeft] = useState(false);
  const confirmNavigation = useUnsavedChanges(Boolean(name));

  return (
    <div>
      <label htmlFor="guarded-name">Name</label>
      <input id="guarded-name" onChange={(event) => setName(event.target.value)} value={name} />
      <button
        onClick={() => {
          if (confirmNavigation()) {
            setLeft(true);
          }
        }}
        type="button"
      >
        Leave
      </button>
      <output>{left ? "Left" : "Editing"}</output>
    </div>
  );
}

describe("form reliability building blocks", () => {
  it("connects labels, descriptions, errors, and invalid state", () => {
    cy.mount(
      <div className="w-[520px] p-6">
        <FormField
          description="Shown to workspace operators."
          error="Enter a provider name."
          htmlFor="provider-name"
          label="Provider name"
          required
        >
          <Input id="provider-name" />
        </FormField>
      </div>
    );

    cy.findByLabelText(/Provider name/)
      .should("have.attr", "aria-invalid", "true")
      .and("have.attr", "aria-describedby")
      .then((describedBy) => {
        const ids = String(describedBy).split(" ");
        expect(ids).to.have.length(2);
        ids.forEach((id) => cy.get(`#${CSS.escape(id)}`).should("be.visible"));
      });
    cy.findByText("Enter a provider name.").should("have.class", "text-destructive");
  });

  it("moves focus from the error summary to the invalid control", () => {
    cy.mount(
      <div className="w-[640px] space-y-4 p-6">
        <FormErrorSummary
          issues={[
            { fieldId: "task-name", label: "Task name", message: "Enter a task name." },
          ]}
        />
        <Input id="task-name" />
      </div>
    );

    cy.findByRole("alert").should("contain.text", "Review the highlighted fields");
    cy.findByRole("button", { name: /Task name: Enter a task name/ }).click();
    cy.get("#task-name").should("have.focus");
  });

  it("keeps section hierarchy and actions compact", () => {
    cy.mount(
      <div className="w-[760px] p-6">
        <StickyFormActions context={<span>Editing provider</span>}>
          <Button variant="outline">Cancel</Button>
          <Button>Save</Button>
        </StickyFormActions>
        <FormSection
          actions={<Button size="sm">Test</Button>}
          description="Connection identity and credentials."
          title="Provider"
        >
          <div>Fields</div>
        </FormSection>
      </div>
    );

    cy.get('[data-slot="sticky-form-actions"]').should("have.class", "min-h-14");
    cy.findByRole("heading", { name: "Provider" }).should("be.visible");
    cy.findByRole("button", { name: "Test" }).should("be.visible");
  });

  it("blocks dirty navigation and allows clean navigation", () => {
    cy.window().then((window) => {
      const confirm = cy.stub(window, "confirm").returns(false);
      cy.wrap(confirm).as("confirm");
    });
    cy.mount(<UnsavedChangesHarness />);

    cy.findByRole("button", { name: "Leave" }).click();
    cy.findByText("Left").should("be.visible");

    cy.mount(<UnsavedChangesHarness />);
    cy.findByLabelText("Name").type("Production provider");
    cy.findByRole("button", { name: "Leave" }).click();
    cy.get("@confirm").should("have.been.calledOnce");
    cy.findByText("Editing").should("be.visible");
  });
});
