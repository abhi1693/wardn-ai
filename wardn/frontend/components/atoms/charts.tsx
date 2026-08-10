"use client";

import dynamic from "next/dynamic";

export const Area = dynamic(() => import("recharts").then((module) => module.Area), {
  ssr: false,
});
export const AreaChart = dynamic(() => import("recharts").then((module) => module.AreaChart), {
  ssr: false,
});
export const Bar = dynamic(() => import("recharts").then((module) => module.Bar), {
  ssr: false,
});
export const BarChart = dynamic(() => import("recharts").then((module) => module.BarChart), {
  ssr: false,
});
export const CartesianGrid = dynamic(
  () => import("recharts").then((module) => module.CartesianGrid),
  { ssr: false }
);
export const Legend = dynamic(() => import("recharts").then((module) => module.Legend), {
  ssr: false,
});
export const Line = dynamic(() => import("recharts").then((module) => module.Line), {
  ssr: false,
});
export const Pie = dynamic(() => import("recharts").then((module) => module.Pie), {
  ssr: false,
});
export const PieChart = dynamic(() => import("recharts").then((module) => module.PieChart), {
  ssr: false,
});
export const ResponsiveContainer = dynamic(
  () => import("recharts").then((module) => module.ResponsiveContainer),
  {
    loading: () => <div className="h-full w-full animate-pulse rounded-md bg-muted" />,
    ssr: false,
  }
);
export const Tooltip = dynamic(() => import("recharts").then((module) => module.Tooltip), {
  ssr: false,
});
export const XAxis = dynamic(() => import("recharts").then((module) => module.XAxis), {
  ssr: false,
});
export const YAxis = dynamic(() => import("recharts").then((module) => module.YAxis), {
  ssr: false,
});
