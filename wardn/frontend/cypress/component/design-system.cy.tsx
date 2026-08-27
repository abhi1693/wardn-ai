import { AlertTriangle, Boxes, Search } from "lucide-react";

import { Button } from "@/components/atoms/button";
import { FeatureMaturityBadge } from "@/components/atoms/feature-maturity-badge";
import { AsyncFeedback } from "@/components/molecules/async-feedback";
import { ConfirmActionDialog } from "@/components/molecules/confirm-action-dialog";
import { DashboardMetricCard } from "@/components/molecules/dashboard-metric-card";
import { EmptyState } from "@/components/molecules/empty-state";
import { SignalBar } from "@/components/molecules/signal-bar";
import { getFeatureMaturity } from "@/lib/feature-maturity";

describe("atomic design details", () => {
  it("defaults features to GA and labels pre-GA maturity explicitly", () => {
    expect(getFeatureMaturity("dashboard")).to.equal("ga");
    expect(getFeatureMaturity("workspace-skills")).to.equal("alpha");
    expect(getFeatureMaturity("workspace-scheduled-tasks")).to.equal("alpha");

    cy.mount(
      <div className="flex gap-2 p-4">
        <FeatureMaturityBadge maturity="alpha" />
        <FeatureMaturityBadge maturity="beta" />
      </div>
    );

    cy.findByLabelText("Feature maturity: Alpha")
      .should("be.visible")
      .and("have.attr", "title")
      .and("contain", "early access");
    cy.findByLabelText("Feature maturity: Beta")
      .should("be.visible")
      .and("have.attr", "title")
      .and("contain", "still being refined");
  });

  it("renders a semantic metric with status and navigation affordances", () => {
    cy.mount(
      <div className="w-80 p-4">
        <DashboardMetricCard
          badge="Healthy"
          detail="12 active, 1 needs review"
          icon={Boxes}
          label="Connections"
          tone="success"
          value="13"
        />
      </div>
    );

    cy.findByText("Connections").should("be.visible");
    cy.findByText("13").should("be.visible").and("have.class", "text-3xl");
    cy.findByText("Healthy").should("be.visible");
    cy.findByText("12 active, 1 needs review").should("be.visible");
    cy.get("svg").should("have.length", 1);
  });

  it("normalizes signal segments and omits zero-value noise", () => {
    cy.mount(
      <div className="w-[400px] p-4">
        <SignalBar
          segments={[
            { label: "8 healthy", tone: "success", value: 8 },
            { label: "2 need review", tone: "warning", value: 2 },
            { label: "0 failed", tone: "danger", value: 0 },
          ]}
        />
      </div>
    );

    cy.findByLabelText("8 healthy").should("have.attr", "style").and("contain", "80%");
    cy.findByLabelText("2 need review").should("have.attr", "style").and("contain", "20%");
    cy.findByLabelText("0 failed").should("not.exist");
  });

  it("keeps empty-state copy concise and its action reachable", () => {
    const onCreate = cy.stub().as("create");
    cy.mount(
      <div className="w-[640px] p-4">
        <EmptyState
          action={<Button onClick={onCreate}>Add connection</Button>}
          description="Connect a server before assigning tools to this workspace."
          icon={Search}
          title="No connections yet"
        />
      </div>
    );

    cy.findByRole("heading", { name: "No connections yet" }).should("be.visible");
    cy.findByRole("button", { name: "Add connection" }).click();
    cy.get("@create").should("have.been.calledOnce");
  });

  it("announces asynchronous failures with the correct live region", () => {
    cy.mount(<AsyncFeedback variant="error">Connection validation failed.</AsyncFeedback>);

    cy.findByRole("alert")
      .should("have.attr", "aria-live", "assertive")
      .and("contain.text", "Connection validation failed.");
  });

  it("keeps a failed confirmation open and exposes the error", () => {
    const onConfirm = cy.stub().rejects(new Error("The connection is still in use."));
    cy.mount(
      <ConfirmActionDialog
        actionLabel="Delete"
        description="This cannot be undone."
        onConfirm={onConfirm}
        title="Delete connection?"
        variant="destructive"
      >
        <Button variant="destructive">Delete connection</Button>
      </ConfirmActionDialog>
    );

    cy.findByRole("button", { name: "Delete connection" }).click();
    cy.findByRole("alertdialog").should("be.visible");
    cy.findByRole("button", { name: "Delete" }).click();
    cy.findByRole("alert").should("contain.text", "The connection is still in use.");
    cy.findByRole("alertdialog").should("be.visible");
    cy.wrap(onConfirm).should("have.been.calledOnce");
  });

  it("closes a successful confirmation and prevents duplicate submission", () => {
    let resolveConfirmation: () => void = () => undefined;
    const onConfirm = cy.stub().callsFake(
      () =>
        new Promise<void>((resolve) => {
          resolveConfirmation = resolve;
        })
    );
    cy.mount(
      <ConfirmActionDialog
        actionLabel="Continue"
        busyLabel="Applying..."
        description="Apply this policy to the workspace."
        onConfirm={onConfirm}
        title="Apply policy?"
      >
        <Button>Apply policy</Button>
      </ConfirmActionDialog>
    );

    cy.findByRole("button", { name: "Apply policy" }).click();
    cy.findByRole("button", { name: "Continue" }).click();
    cy.findByRole("button", { name: "Applying..." }).should("be.disabled");
    cy.wrap(onConfirm).should("have.been.calledOnce");
    cy.then(() => resolveConfirmation());
    cy.findByRole("alertdialog").should("not.exist");
  });

  it("keeps destructive context visually distinct", () => {
    cy.mount(
      <div className="flex items-center gap-3 p-4 text-red-700">
        <AlertTriangle aria-label="Warning" className="size-4" />
        <span>Permanent action</span>
      </div>
    );
    cy.findByLabelText("Warning").should("be.visible");
    cy.findByText("Permanent action").parent().should("have.class", "text-red-700");
  });
});
