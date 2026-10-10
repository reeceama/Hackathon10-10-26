// Pages Referee never captures, shared by content.js (web pages) and background.js (PDFs):
// search results, email, writing tools, social media, banking, payment and login pages.

const SKIP = [
  /\/\/(www\.)?google\.[^/]+\/search/,
  /\/\/(www\.)?bing\.com\/search/,
  /\/\/scholar\.google\./,
  /\/\/(mail|outlook|calendar|docs|drive)\./,
  /\/\/([^/]+\.)?(notion\.so|office\.com|live\.com|sharepoint\.com|overleaf\.com)\//,
  /\/\/([^/]+\.)?(facebook|instagram|twitter|x|tiktok|reddit|youtube|linkedin)\.com\//,
  /\/\/localhost[:/]/,
  /\/\/([^/]+\.)?(paypal|stripe|monzo|revolut|starlingbank|barclays|hsbc|natwest|lloydsbank|santander|nationwide|halifax|chase|wellsfargo|bankofamerica)\.(com|co\.uk)\//,
  /\/\/[^/]*(bank|banking)[^/]*\//,
  /\/(login|signin|sign-in|checkout|payment|account)(\/|\?|$)/,
];

function isSkipped(url) {
  return SKIP.some((pattern) => pattern.test(url));
}
