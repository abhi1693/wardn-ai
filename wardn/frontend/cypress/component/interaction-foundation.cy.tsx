import { MoreHorizontal } from "lucide-react";
import { toast } from "sonner";

import { Button } from "@/components/atoms/button";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuTrigger,
} from "@/components/atoms/dropdown-menu";
import { Toaster } from "@/components/atoms/sonner";
import {
  Tooltip,
  TooltipContent,
  TooltipTrigger,
} from "@/components/atoms/tooltip";
import {
  DesktopCommandMenu,
  type CommandDestination,
} from "@/components/organisms/desktop-command-menu";

const destinations: CommandDestination[] = [
  { group: "Assistant", href: "/workspace/chat", label: "Chat" },
  { group: "Capabilities", href: "/workspace/connections", label: "Connections" },
  { group: "Operations", href: "/workspace/runs", label: "Runs" },
];

describe("desktop interaction foundation", () => {
  it("opens the command menu from the keyboard and filters destinations", () => {
    const onNavigate = cy.stub().as("navigate");
    cy.mount(<DesktopCommandMenu destinations={destinations} onNavigate={onNavigate} />);

    cy.get("body").trigger("keydown", { ctrlKey: true, key: "k" });
    cy.findByRole("dialog", { name: "Command menu" }).should("be.visible");
    cy.findByRole("combobox", { name: "Search destinations" }).should("be.focused").type("conn");
    cy.findByText("Connections").should("be.visible");
    cy.findByText("Chat").should("not.exist");
    cy.findByRole("combobox", { name: "Search destinations" }).type("{enter}");

    cy.get("@navigate").should("have.been.calledOnceWith", "/workspace/connections");
    cy.findByRole("dialog", { name: "Command menu" }).should("not.exist");
  });

  it("opens from the visible shell control and reports an empty search", () => {
    cy.mount(<DesktopCommandMenu destinations={destinations} onNavigate={cy.stub()} />);

    cy.findByRole("button", { name: "Open command menu" }).click();
    cy.findByRole("combobox", { name: "Search destinations" }).type("not available");
    cy.findByText("No matching destination.").should("be.visible");
    cy.get("body").type("{esc}");
    cy.findByRole("dialog", { name: "Command menu" }).should("not.exist");
  });

  it("shows a tooltip for a focused icon control", () => {
    cy.mount(
      <Tooltip>
        <TooltipTrigger asChild>
          <Button aria-label="More actions" size="icon" variant="outline">
            <MoreHorizontal className="size-4" />
          </Button>
        </TooltipTrigger>
        <TooltipContent>More actions</TooltipContent>
      </Tooltip>
    );

    cy.findByRole("button", { name: "More actions" }).focus();
    cy.findByRole("tooltip").should("be.visible").and("contain.text", "More actions");
  });

  it("supports keyboard selection in a dropdown menu", () => {
    const onEdit = cy.stub().as("edit");
    cy.mount(
      <DropdownMenu>
        <DropdownMenuTrigger asChild>
          <Button aria-label="Connection actions" size="icon" variant="outline">
            <MoreHorizontal className="size-4" />
          </Button>
        </DropdownMenuTrigger>
        <DropdownMenuContent>
          <DropdownMenuItem onSelect={onEdit}>Edit connection</DropdownMenuItem>
          <DropdownMenuItem>View activity</DropdownMenuItem>
        </DropdownMenuContent>
      </DropdownMenu>
    );

    cy.findByRole("button", { name: "Connection actions" }).focus().type("{enter}");
    cy.findByRole("menu").should("be.visible");
    cy.findByRole("menuitem", { name: "Edit connection" }).type("{enter}");
    cy.get("@edit").should("have.been.calledOnce");
  });

  it("renders theme-aware success feedback without shifting page content", () => {
    cy.mount(
      <>
        <Button onClick={() => toast.success("Connection saved")}>Save connection</Button>
        <Toaster position="bottom-right" />
      </>
    );

    cy.findByRole("button", { name: "Save connection" }).click();
    cy.findByText("Connection saved").should("be.visible");
    cy.get('[data-sonner-toaster]').should("have.attr", "data-y-position", "bottom");
  });
});
