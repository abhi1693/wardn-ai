const selectionCookieMaxAgeSeconds = 365 * 24 * 60 * 60;

export function setSelectionCookie(
  name: string,
  value: string,
  maxAge = selectionCookieMaxAgeSeconds
) {
  document.cookie = `${name}=${encodeURIComponent(value)}; path=/; max-age=${maxAge}; samesite=lax`;
}

export function clearSelectionCookie(name: string) {
  setSelectionCookie(name, "", 0);
}
