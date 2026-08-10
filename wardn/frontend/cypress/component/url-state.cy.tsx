import { useUrlState } from "@/hooks/use-url-state";

function UrlStateHarness() {
  const [query, setQuery] = useUrlState("connections-query");
  const [status, setStatus] = useUrlState("connections-status", "all");
  return (
    <div>
      <label htmlFor="query">Query</label>
      <input id="query" onChange={(event) => setQuery(event.target.value)} value={query} />
      <button onClick={() => setStatus(status === "all" ? "failed" : "all")} type="button">
        {status}
      </button>
    </div>
  );
}

describe("useUrlState", () => {
  beforeEach(() => {
    window.history.replaceState({}, "", "/url-state");
  });

  it("writes independent list controls without dropping unrelated query parameters", () => {
    window.history.replaceState({}, "", "/url-state?source=workspace");
    cy.mount(<UrlStateHarness />);
    cy.findByLabelText("Query").type("runtime");
    cy.findByRole("button", { name: "all" }).click();
    cy.location("search")
      .should("contain", "source=workspace")
      .and("contain", "connections-query=runtime")
      .and("contain", "connections-status=failed");
  });

  it("restores values and removes default values from the URL", () => {
    window.history.replaceState(
      {},
      "",
      "/url-state?connections-query=search&connections-status=failed"
    );
    cy.mount(<UrlStateHarness />);
    cy.findByLabelText("Query").should("have.value", "search");
    cy.findByRole("button", { name: "failed" }).click();
    cy.location("search").should("not.contain", "connections-status");
  });
});
