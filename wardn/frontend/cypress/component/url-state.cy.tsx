import Link from "next/link";

import { useUrlState } from "@/hooks/use-url-state";
import { NavigationStateRestoration } from "@/components/providers/navigation-state-restoration";

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
    window.sessionStorage.clear();
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

  it("restores cached controls after a form returns to the bare list URL", () => {
    cy.mount(<UrlStateHarness />);
    cy.findByLabelText("Query").type("runtime");
    cy.findByRole("button", { name: "all" }).click();

    cy.then(() => window.history.replaceState({}, "", "/detail/edit"));
    cy.mount(<div>Editing</div>);
    cy.then(() => window.history.replaceState({}, "", "/url-state"));
    cy.mount(<UrlStateHarness />);

    cy.findByLabelText("Query").should("have.value", "runtime");
    cy.findByRole("button", { name: "failed" }).should("be.visible");
    cy.location("search")
      .should("contain", "connections-query=runtime")
      .and("contain", "connections-status=failed");
  });

  it("restores scroll position when returning from a detail view", () => {
    const page = (pathname: string) => (
      <>
        <NavigationStateRestoration pathname={pathname} />
        <div style={{ height: "3000px", paddingTop: "700px" }}>
          <Link href="/records/one" onClick={(event) => event.preventDefault()}>
            Open record
          </Link>
          {pathname}
        </div>
      </>
    );

    cy.mount(page("/records"));
    cy.scrollTo(0, 640);
    cy.window().its("scrollY").should("be.greaterThan", 600);
    cy.findByRole("link", { name: "Open record" }).click();
    cy.window()
      .its("sessionStorage")
      .invoke("getItem", "wardn:scroll-position:v1:/records")
      .then((value) => expect(Number(value)).to.be.greaterThan(600));
    cy.mount(page("/records/one"));
    cy.scrollTo(0, 0);
    cy.mount(page("/records"));
    cy.window().its("scrollY").should("be.greaterThan", 600);
  });
});
