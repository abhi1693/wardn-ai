import { useState } from "react";

import { Button } from "@/components/atoms/button";
import { DeferredRender } from "@/components/molecules/deferred-render";
import { EditorLoading } from "@/components/molecules/editor-loading";
import { apiRawFetch } from "@/lib/api/client";
import { reportFrontendMetric, telemetryPath } from "@/lib/frontend-telemetry";

function MetricHarness() {
  return (
    <div className="space-y-3 p-6">
      <Button
        onClick={() =>
          reportFrontendMetric({
            kind: "navigation",
            name: "test-transition",
            path: "/org/2d12c876-d687-4fc4-ae61-f55bf9c05c56/runs?secret=value",
            value: 42,
          })
        }
      >
        Report navigation
      </Button>
    </div>
  );
}

function ApiTimingHarness() {
  const [status, setStatus] = useState("Idle");
  return (
    <Button
      onClick={() => {
        void apiRawFetch("/api/test-resource?token=private").then(() => setStatus("Complete"));
      }}
    >
      {status}
    </Button>
  );
}

describe("performance and observability", () => {
  it("normalizes telemetry paths before sending browser metrics", () => {
    expect(
      telemetryPath(
        "/org/2d12c876-d687-4fc4-ae61-f55bf9c05c56/run-run-123?secret=value"
      )
    ).to.equal("/org/:id/run-:id");

    cy.window().then((window) => {
      const sendBeacon = cy.stub(window.navigator, "sendBeacon").returns(true);
      cy.wrap(sendBeacon).as("sendBeacon");
    });
    cy.mount(<MetricHarness />);
    cy.findByRole("button", { name: "Report navigation" }).click();
    cy.get("@sendBeacon").should((beacon) => {
      const [path, body] = (beacon as unknown as { firstCall: { args: unknown[] } }).firstCall.args;
      expect(path).to.equal("/api/frontend-telemetry");
      expect(JSON.parse(String(body))).to.include({
        kind: "navigation",
        path: "/org/:id/runs",
        value: 42,
      });
    });
  });

  it("records shared API transport duration without leaking query values", () => {
    cy.mount(<ApiTimingHarness />);
    cy.window().then((window) => {
      cy.stub(window, "fetch").resolves(new Response(null, { status: 204 }));
      const sendBeacon = cy.stub(window.navigator, "sendBeacon").returns(true);
      cy.wrap(sendBeacon).as("sendBeacon");
    });
    cy.findByRole("button", { name: "Idle" }).click();
    cy.findByRole("button", { name: "Complete" }).should("be.visible");
    cy.get("@sendBeacon").should((beacon) => {
      const body = (beacon as unknown as { firstCall: { args: unknown[] } }).firstCall.args[1];
      const payload = JSON.parse(String(body));
      expect(payload).to.include({ kind: "api", name: "request", path: "/api/test-resource" });
      expect(payload.detail).to.deep.equal({ method: "GET", status: 204 });
      expect(payload.value).to.be.at.least(0);
    });
  });

  it("defers offscreen rendering for long variable-height collections", () => {
    cy.mount(
      <div className="h-72 overflow-auto p-4">
        {Array.from({ length: 500 }, (_, index) => (
          <DeferredRender
            className="border-b px-3 py-2"
            estimatedHeight={48}
            key={index}
          >
            Event {index + 1}
          </DeferredRender>
        ))}
      </div>
    );

    cy.get("[data-deferred-render]").should("have.length", 500);
    cy.get("[data-deferred-render]")
      .last()
      .should("have.css", "content-visibility", "auto")
      .and("have.css", "contain-intrinsic-size", "auto 48px");
  });

  it("reserves a stable desktop editor layout while heavy clients load", () => {
    cy.mount(<EditorLoading label="Loading provider editor" />);
    cy.findByRole("status", { name: "Loading provider editor" }).should("be.visible");
    cy.findByRole("status").children().eq(1).should("have.css", "min-height", "420px");
  });
});
