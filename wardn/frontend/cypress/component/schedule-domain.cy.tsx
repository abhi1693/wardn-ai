import {
  configNumberList,
  configTimes,
  newScheduleDraft,
  normalizeTimezone,
  scheduleDraftConfig,
  scheduleDraftIsValid,
} from "@/app/org/[organizationId]/workspace/[workspaceId]/scheduled-tasks/_lib/schedule-domain";

describe("scheduled task domain", () => {
  it("normalizes legacy timezone and schedule config values", () => {
    expect(normalizeTimezone("Asia/Calcutta")).to.equal("Asia/Kolkata");
    expect(configTimes({ times: ["17:00", "09:00", "09:00"] })).to.deep.equal([
      "09:00",
      "17:00",
    ]);
    expect(configNumberList({ weekdays: [4, 0, 4] }, "weekdays", "weekday", [0])).to.deep.equal([
      "4",
      "0",
    ]);
  });

  it("creates predictable drafts and validates schedule boundaries", () => {
    const daily = newScheduleDraft("daily", "UTC", "daily-test");
    expect(daily).to.include({ key: "daily-test", scheduleType: "daily", timezone: "UTC" });
    expect(scheduleDraftIsValid(daily)).to.equal(true);

    const invalidInterval = { ...newScheduleDraft("interval", "UTC"), everyMinutes: "0" };
    expect(scheduleDraftIsValid(invalidInterval)).to.equal(false);

    const invalidWindow = {
      ...daily,
      endsAt: "2026-08-10T09:00",
      startsAt: "2026-08-11T09:00",
    };
    expect(scheduleDraftIsValid(invalidWindow)).to.equal(false);
  });

  it("serializes each schedule type to the API shape", () => {
    const weekly = {
      ...newScheduleDraft("weekly", "UTC"),
      times: ["14:00", "09:00"],
      weekdays: ["4", "0"],
    };
    expect(scheduleDraftConfig(weekly)).to.deep.equal({
      times: ["14:00", "09:00"],
      weekdays: [0, 4],
    });

    const cron = { ...newScheduleDraft("cron", "UTC"), cronExpression: " 0 9 * * 1-5 " };
    expect(scheduleDraftConfig(cron)).to.deep.equal({ expression: "0 9 * * 1-5" });
  });
});
