import { describe, expect, test } from "vitest";
import { detectMobile } from "./detectMobile";

// Representative UA formats from Mozilla, WebKit, Chromium, and Microsoft documentation:
// https://developer.mozilla.org/en-US/docs/Web/HTTP/Reference/Headers/User-Agent
const mobileUserAgents = [
  {
    name: "Firefox OS with only the Mobile token",
    userAgent: "Mozilla/5.0 (Mobile; rv:26.0) Gecko/26.0 Firefox/26.0"
  },
  {
    name: "iPhone Safari",
    userAgent:
      "Mozilla/5.0 (iPhone; CPU iPhone OS 17_5 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.5 Mobile/15E148 Safari/604.1"
  },
  {
    name: "legacy iPad Safari",
    userAgent:
      "Mozilla/5.0 (iPad; CPU OS 12_5_7 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/12.0 Mobile/15E148 Safari/604.1"
  },
  {
    name: "Android Chrome",
    userAgent:
      "Mozilla/5.0 (Linux; Android 14; Pixel 8 Pro) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Mobile Safari/537.36"
  },
  {
    name: "Firefox on Android",
    userAgent: "Mozilla/5.0 (Android 14; Mobile; rv:126.0) Gecko/126.0 Firefox/126.0"
  },
  {
    name: "Internet Explorer Mobile",
    userAgent: "Mozilla/4.0 (compatible; MSIE 7.0; Windows Phone OS 7.5; Trident/5.0; IEMobile/9.0)"
  }
] as const;

const desktopUserAgents = [
  {
    name: "iPadOS Safari in desktop mode",
    userAgent:
      "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/13.0 Safari/605.1.15"
  },
  {
    name: "Chrome on Windows",
    userAgent:
      "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36"
  },
  {
    name: "Safari on macOS",
    userAgent:
      "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.5 Safari/605.1.15"
  },
  {
    name: "Firefox on Windows",
    userAgent: "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:126.0) Gecko/20100101 Firefox/126.0"
  },
  {
    name: "Edge on Windows",
    userAgent:
      "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36 Edg/126.0.0.0"
  }
] as const;

describe("detectMobile", () => {
  test.each(mobileUserAgents)("detects $name", ({ userAgent }) => {
    expect(detectMobile(userAgent)).toBe(true);
  });

  test.each(desktopUserAgents)("does not detect $name", ({ userAgent }) => {
    expect(detectMobile(userAgent)).toBe(false);
  });
});
