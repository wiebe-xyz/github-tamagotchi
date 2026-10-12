// Starts browser tracing: web vitals, fetch spans with traceparent, navigation and errors.
// Spans go to our own /api/v1/telemetry proxy, which adds the SpanBarn API key server-side,
// so no key is present in the browser.
(function () {
  try {
    if (!window.SpanBarnSDK) return;
    window.SpanBarnSDK.SpanBarn.init({
      endpoint: "/api/v1/telemetry",
      apiKey: "proxy",
      service: "github-tamagotchi-web",
    });
    window.SpanBarnSDK.instrumentBrowser({
      webVitals: true,
      fetch: true,
      navigation: true,
      errors: true,
    });
  } catch (e) {
    /* tracing must never break the page */
  }
})();
