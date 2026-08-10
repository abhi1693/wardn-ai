"use client";

import dynamic from "next/dynamic";

import { EditorLoading } from "@/components/molecules/editor-loading";

export const ChatProviderFormLoader = dynamic(
  () => import("../provider-form-client").then((module) => module.ChatProviderFormClient),
  {
    loading: () => <EditorLoading label="Loading chat provider editor" />,
    ssr: false,
  }
);
