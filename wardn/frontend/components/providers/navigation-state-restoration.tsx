"use client";

import { usePathname } from "next/navigation";
import { useEffect } from "react";

const storagePrefix = "wardn:scroll-position:v1";

function scrollStorageKey(pathname: string) {
  return `${storagePrefix}:${pathname}`;
}

function readScrollPosition(pathname: string) {
  try {
    return Number(window.sessionStorage.getItem(scrollStorageKey(pathname))) || 0;
  } catch {
    return 0;
  }
}

function writeScrollPosition(pathname: string) {
  try {
    window.sessionStorage.setItem(scrollStorageKey(pathname), String(Math.max(0, window.scrollY)));
  } catch {
    // Navigation remains functional when session storage is unavailable.
  }
}

export function NavigationStateRestoration({ pathname: pathnameOverride }: { pathname?: string }) {
  const currentPathname = usePathname();
  const pathname = pathnameOverride ?? currentPathname;

  useEffect(() => {
    const previousScrollRestoration = window.history.scrollRestoration;
    window.history.scrollRestoration = "manual";
    const savedPosition = readScrollPosition(pathname);
    let restoring = savedPosition > 0;
    let frame = 0;
    let pendingZeroWrite = 0;

    const restore = () => {
      if (!restoring) {
        return;
      }
      window.scrollTo(0, savedPosition);
    };
    frame = window.requestAnimationFrame(restore);
    const resizeObserver = new ResizeObserver(restore);
    resizeObserver.observe(document.documentElement);
    const restoreInterval = window.setInterval(restore, 100);
    const stopRestoring = window.setTimeout(() => {
      restoring = false;
      window.clearInterval(restoreInterval);
      resizeObserver.disconnect();
    }, 1_000);
    const cancelRestoring = () => {
      restoring = false;
      window.clearInterval(restoreInterval);
      resizeObserver.disconnect();
    };
    const remember = () => {
      if (restoring) {
        return;
      }
      window.clearTimeout(pendingZeroWrite);
      if (window.scrollY === 0) {
        pendingZeroWrite = window.setTimeout(() => writeScrollPosition(pathname), 250);
      } else {
        writeScrollPosition(pathname);
      }
    };
    const rememberBeforeNavigation = (event: MouseEvent) => {
      const target = event.target instanceof Element ? event.target.closest<HTMLAnchorElement>("a[href]") : null;
      if (!target || target.target === "_blank") {
        return;
      }
      const destination = new URL(target.href, window.location.href);
      if (destination.origin === window.location.origin) {
        window.clearTimeout(pendingZeroWrite);
        writeScrollPosition(pathname);
      }
    };
    window.addEventListener("scroll", remember, { passive: true });
    window.addEventListener("pagehide", remember);
    document.addEventListener("click", rememberBeforeNavigation, true);
    window.addEventListener("keydown", cancelRestoring);
    window.addEventListener("pointerdown", cancelRestoring, { passive: true });
    window.addEventListener("touchstart", cancelRestoring, { passive: true });
    window.addEventListener("wheel", cancelRestoring, { passive: true });

    return () => {
      // Next.js may reset the document to the top before this route unmounts.
      // Keep the last meaningful position instead of overwriting it with that
      // navigation-induced zero.
      if (window.scrollY > 0) {
        writeScrollPosition(pathname);
      }
      window.cancelAnimationFrame(frame);
      window.clearInterval(restoreInterval);
      window.clearTimeout(stopRestoring);
      window.clearTimeout(pendingZeroWrite);
      resizeObserver.disconnect();
      window.removeEventListener("scroll", remember);
      window.removeEventListener("pagehide", remember);
      document.removeEventListener("click", rememberBeforeNavigation, true);
      window.removeEventListener("keydown", cancelRestoring);
      window.removeEventListener("pointerdown", cancelRestoring);
      window.removeEventListener("touchstart", cancelRestoring);
      window.removeEventListener("wheel", cancelRestoring);
      window.history.scrollRestoration = previousScrollRestoration;
    };
  }, [pathname]);

  return null;
}
