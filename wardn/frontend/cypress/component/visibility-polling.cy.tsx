import { useVisibilityPolling } from "@/hooks/use-visibility-polling";

function PollingHarness({
  enabled = true,
  onError,
  poll,
}: {
  enabled?: boolean;
  onError?: (error: unknown) => void;
  poll: (signal: AbortSignal) => Promise<void>;
}) {
  useVisibilityPolling({
    enabled,
    intervalMs: 1_000,
    maxIntervalMs: 4_000,
    onError,
    poll,
  });
  return <div>Polling harness</div>;
}

describe("visibility-aware polling", () => {
  afterEach(() => {
    Object.defineProperty(document, "visibilityState", {
      configurable: true,
      value: "visible",
    });
  });

  it("pauses while hidden and refreshes immediately when visible", () => {
    Object.defineProperty(document, "visibilityState", {
      configurable: true,
      value: "hidden",
    });
    const poll = cy.stub().resolves();

    cy.mount(<PollingHarness poll={poll} />);
    cy.wrap(poll).should("not.have.been.called");

    cy.document().then((document) => {
      Object.defineProperty(document, "visibilityState", {
        configurable: true,
        value: "visible",
      });
      document.dispatchEvent(new Event("visibilitychange"));
    });
    cy.wrap(poll).should("have.been.calledOnce");
  });

  it("backs off after a failed poll", () => {
    cy.clock();
    const poll = cy.stub();
    poll.onFirstCall().rejects(new Error("temporary failure"));
    poll.resolves();
    const onError = cy.stub();

    cy.mount(<PollingHarness onError={onError} poll={poll} />);
    cy.wrap(poll).should("have.been.calledOnce");
    cy.wrap(onError).should("have.been.calledOnce");

    cy.tick(1_999);
    cy.wrap(poll).should("have.been.calledOnce");
    cy.tick(1);
    cy.wrap(poll).should("have.been.calledTwice");
  });

  it("aborts an in-flight poll when the page becomes hidden", () => {
    let activeSignal: AbortSignal | undefined;
    const poll = cy.stub().callsFake((signal: AbortSignal) => {
      activeSignal = signal;
      return new Promise<void>(() => undefined);
    });

    cy.mount(<PollingHarness poll={poll} />);
    cy.wrap(poll).should("have.been.calledOnce");
    cy.then(() => expect(activeSignal?.aborted).to.equal(false));

    cy.document().then((document) => {
      Object.defineProperty(document, "visibilityState", {
        configurable: true,
        value: "hidden",
      });
      document.dispatchEvent(new Event("visibilitychange"));
    });
    cy.then(() => expect(activeSignal?.aborted).to.equal(true));
  });
});
