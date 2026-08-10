"use client";

import dynamic from "next/dynamic";

import { EditorLoading } from "@/components/molecules/editor-loading";

export const ScheduledTaskFormLoader = dynamic(
  () =>
    import("../scheduled-tasks-client").then((module) => module.ScheduledTaskFormClient),
  {
    loading: () => <EditorLoading label="Loading scheduled task editor" />,
    ssr: false,
  }
);
