"use client";

import { Moon, Sun } from "lucide-react";
import { useTheme } from "next-themes";
import { useSyncExternalStore } from "react";

import { Button } from "@/components/atoms/button";

const subscribeToHydration = () => () => undefined;
const getClientSnapshot = () => true;
const getServerSnapshot = () => false;

export function ThemeSwitcher() {
  const mounted = useSyncExternalStore(
    subscribeToHydration,
    getClientSnapshot,
    getServerSnapshot
  );
  const { resolvedTheme, setTheme, theme } = useTheme();
  const currentTheme = theme === "system" ? resolvedTheme : theme;
  const nextTheme = currentTheme === "dark" ? "light" : "dark";

  if (!mounted) {
    return (
      <Button
        aria-label="Change theme"
        className="relative"
        disabled
        size="icon"
        type="button"
        variant="ghost"
      >
        <Sun className="size-4" />
      </Button>
    );
  }

  return (
    <Button
      aria-label={`Switch to ${nextTheme} theme`}
      className="relative"
      onClick={() => setTheme(nextTheme)}
      size="icon"
      title={`Switch to ${nextTheme} theme`}
      type="button"
      variant="ghost"
    >
      <Sun className="size-4 rotate-0 scale-100 transition-transform dark:-rotate-90 dark:scale-0" />
      <Moon className="absolute size-4 rotate-90 scale-0 transition-transform dark:rotate-0 dark:scale-100" />
    </Button>
  );
}
