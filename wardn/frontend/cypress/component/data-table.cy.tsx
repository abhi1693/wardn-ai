import { Button } from "@/components/atoms/button";
import { DataTableColumnHeader } from "@/components/molecules/data-table-column-header";
import {
  DataTable,
  type DataTableColumnDef,
} from "@/components/organisms/data-table";

type Operation = {
  id: string;
  name: string;
  owner: string;
  status: "failed" | "running" | "succeeded";
};

const operations: Operation[] = [
  { id: "1", name: "Alpha sync", owner: "Ada", status: "succeeded" },
  { id: "2", name: "Beta export", owner: "Ben", status: "failed" },
  { id: "3", name: "Gamma review", owner: "Cara", status: "running" },
  { id: "4", name: "Delta report", owner: "Dev", status: "succeeded" },
  { id: "5", name: "Epsilon audit", owner: "Eli", status: "failed" },
];

const columns: DataTableColumnDef<Operation>[] = [
  {
    accessorKey: "name",
    header: ({ column }) => (
      <DataTableColumnHeader column={column} title="Operation" />
    ),
  },
  { accessorKey: "status", header: "Status" },
  { accessorKey: "owner", header: "Owner" },
];

function OperationsTable() {
  return (
    <div className="w-[960px] p-6">
      <DataTable
        bulkActions={(rows) => <Button size="sm">Retry {rows.length}</Button>}
        columns={columns}
        data={operations}
        filters={[
          {
            columnId: "status",
            label: "Status",
            options: [
              { label: "Failed", value: "failed" },
              { label: "Running", value: "running" },
              { label: "Succeeded", value: "succeeded" },
            ],
          },
        ]}
        getRowId={(row) => row.id}
        pageSize={2}
        search={{ columnId: "name", placeholder: "Search operations" }}
        selectable
        urlSyncKey="ops"
      />
    </div>
  );
}

describe("DataTable", () => {
  beforeEach(() => {
    window.history.replaceState({}, "", "/data-table");
  });

  it("sorts, filters, paginates, and writes restorable URL state", () => {
    cy.mount(<OperationsTable />);
    cy.findByText("Page 1 of 3").should("be.visible");
    cy.findByRole("button", { name: "Sort by Operation" }).click();
    cy.location("search").should("contain", "ops-sort=name");

    cy.findByLabelText("Search operations").type("report");
    cy.findByText("Delta report").should("be.visible");
    cy.findByText("1 records").should("be.visible");
    cy.location("search").should("contain", "ops-query=report");

    cy.findByRole("button", { name: "Clear" }).click();
    cy.findByRole("button", { name: "Next page" }).click();
    cy.findByText("Page 2 of 3").should("be.visible");
    cy.location("search").should("contain", "ops-page=2");
  });

  it("restores filters and hidden columns from the URL", () => {
    window.history.replaceState(
      {},
      "",
      "/data-table?ops-query=beta&ops-status=failed&ops-hidden=owner"
    );
    cy.mount(<OperationsTable />);

    cy.findByLabelText("Search operations").should("have.value", "beta");
    cy.findByText("Beta export").should("be.visible");
    cy.findByRole("columnheader", { name: "Owner" }).should("not.exist");
    cy.findByText("1 records").should("be.visible");
  });

  it("selects visible rows and exposes bulk actions", () => {
    cy.mount(<OperationsTable />);
    cy.findByRole("checkbox", { name: "Select all visible rows" }).click();
    cy.findByText("2 selected").should("be.visible");
    cy.findByRole("button", { name: "Retry 2" }).should("be.visible");

    cy.findAllByRole("checkbox", { name: "Select row" }).first().click();
    cy.findByText("1 selected").should("be.visible");
  });

  it("toggles column visibility from the keyboard-accessible menu", () => {
    cy.mount(<OperationsTable />);
    cy.findByRole("button", { name: "Columns" }).click();
    cy.findByRole("menuitemcheckbox", { name: "owner" }).click();
    cy.findByRole("columnheader", { name: "Owner" }).should("not.exist");
    cy.location("search").should("contain", "ops-hidden=owner");
  });

  it("bounds rendered rows for large client datasets", () => {
    const largeDataset = Array.from({ length: 1_000 }, (_, index) => ({
      id: String(index),
      name: `Operation ${index + 1}`,
      owner: `Owner ${index + 1}`,
      status: "succeeded" as const,
    }));
    cy.mount(
      <div className="w-[960px] p-6">
        <DataTable columns={columns} data={largeDataset} pageSize={20} />
      </div>
    );

    cy.findByText("1,000 records").should("be.visible");
    cy.findByText("Page 1 of 50").should("be.visible");
    cy.get("tbody tr").should("have.length", 20);
  });
});
