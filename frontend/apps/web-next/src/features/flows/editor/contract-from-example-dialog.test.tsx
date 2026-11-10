// @vitest-environment jsdom
import { cleanup, fireEvent, screen, waitFor } from "@testing-library/react";
import { afterEach, expect, it } from "vitest";
import messages from "@/lib/i18n/messages/sv.json";
import { renderInApp } from "@/test/render";
import { ContractFromExampleDialog } from "./contract-from-example-dialog";

afterEach(cleanup);

it("opens with focus in the example field, where the author pastes", async () => {
  renderInApp(<ContractFromExampleDialog current={null} onAccept={() => {}} />);
  fireEvent.click(
    screen.getByRole("button", { name: messages.flow_editor_tools_contract_example_button })
  );
  const field = await screen.findByLabelText(/^Exempel på svar/);
  await waitFor(() => expect(document.activeElement).toBe(field));
});
