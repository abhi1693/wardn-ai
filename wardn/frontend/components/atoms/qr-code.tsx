"use client";

import dynamic from "next/dynamic";

export const QRCode = dynamic(
  () => import("qrcode.react").then((module) => module.QRCodeSVG),
  {
    loading: () => <div className="aspect-square w-full animate-pulse rounded-md bg-muted" />,
    ssr: false,
  }
);
